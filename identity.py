"""BOLT identity layer — user profile, fact learning, and context relay.

This is what makes BOLT feel like one entity across all models.
Every model gets an identity briefing before it speaks — user profile,
current mode, and a handoff from whatever brain region was active before.
"""

import json
import time
import threading
import sqlite3
import os
import requests

from config import (
    MODELS, OLLAMA_URL, BOLT_IDENTITY,
    COMPANION_CONTEXT, BUILD_CONTEXT, CODE_CONTEXT,
    PROFILE_EXTRACT_PROMPT, HANDOFF_PROMPT,
    PROFILE_INTERVAL,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bolt.db")

_local = threading.local()


def _get_conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


# ─── DB setup ───

def init_profile_tables():
    """Create profile tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 0.5,
            source TEXT,
            created_at DATETIME DEFAULT (datetime('now')),
            updated_at DATETIME DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );

        CREATE TABLE IF NOT EXISTS context_relay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT (datetime('now')),
            from_model TEXT,
            to_model TEXT,
            handoff TEXT NOT NULL,
            session_id TEXT
        );
    """)
    conn.commit()


# ─── User Profile ───

def get_profile():
    """Get the full user profile as a dict of {category: {key: {value, confidence}}}."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT category, key, value, confidence FROM user_profile ORDER BY category, key"
    ).fetchall()
    profile = {}
    for r in rows:
        cat = r["category"]
        if cat not in profile:
            profile[cat] = {}
        profile[cat][r["key"]] = {"value": r["value"], "confidence": r["confidence"]}
    return profile


def get_profile_text():
    """Get user profile as a readable string for injection into prompts."""
    profile = get_profile()
    if not profile:
        return "You don't know much about this user yet. Pay attention and learn naturally."

    lines = ["What you know about this user:"]
    for cat, facts in profile.items():
        items = [f"{k}: {v['value']}" for k, v in facts.items()]
        lines.append(f"  {cat}: {', '.join(items)}")
    lines.append("Use this naturally — don't recite it back. Just let it inform how you talk to them.")
    return "\n".join(lines)


def get_profile_display():
    """Get user profile formatted for the /profile command."""
    profile = get_profile()
    if not profile:
        return "BOLT hasn't learned much about you yet. Keep chatting!"

    lines = []
    for cat, facts in profile.items():
        lines.append(f"  {cat.upper()}")
        for k, v in facts.items():
            conf = "●" * int(v["confidence"] * 5) + "○" * (5 - int(v["confidence"] * 5))
            lines.append(f"    {k}: {v['value']}  [{conf}]")
    return "\n".join(lines)


def save_fact(category, key, value, confidence=0.5, source=None):
    """Save or update a profile fact. Higher confidence wins."""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT confidence FROM user_profile WHERE category = ? AND key = ?",
        (category, key),
    ).fetchone()

    if existing:
        # Only update if new confidence is higher or equal (fresher data)
        if confidence >= existing["confidence"]:
            conn.execute(
                "UPDATE user_profile SET value=?, confidence=?, source=?, updated_at=datetime('now') "
                "WHERE category=? AND key=?",
                (value, confidence, source, category, key),
            )
    else:
        conn.execute(
            "INSERT INTO user_profile (category, key, value, confidence, source) VALUES (?, ?, ?, ?, ?)",
            (category, key, value, confidence, source),
        )
    conn.commit()


def forget_fact(category, key):
    """Remove a specific fact (for user control over their profile)."""
    conn = _get_conn()
    conn.execute("DELETE FROM user_profile WHERE category = ? AND key = ?", (category, key))
    conn.commit()


def clear_profile():
    """Wipe the entire profile (user requested reset)."""
    conn = _get_conn()
    conn.execute("DELETE FROM user_profile")
    conn.commit()


# ─── Profile learner ───

def _ollama_generate(model, prompt, timeout=120):
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception:
        pass
    return ""


def learn_from_conversation(conversation_text, source="conversation"):
    """Extract facts from a conversation and save to profile.

    Runs on the small model to be fast and cheap. Called in the background
    so it never blocks the user.
    """
    profile = get_profile()
    # Flatten existing profile for the prompt
    existing = []
    for cat, facts in profile.items():
        for k, v in facts.items():
            existing.append(f"{cat}/{k}: {v['value']}")
    existing_text = "\n".join(existing) if existing else "(empty profile)"

    prompt = PROFILE_EXTRACT_PROMPT.format(
        existing_profile=existing_text,
        conversation=conversation_text[:2000],
    )

    raw = _ollama_generate(MODELS["router"], prompt)
    if not raw.strip():
        return 0

    # Parse the JSON list of facts
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return 0
        facts = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return 0

    count = 0
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        cat = fact.get("category", "").strip()
        key = fact.get("key", "").strip()
        val = fact.get("value", "").strip()
        conf = float(fact.get("confidence", 0.5))
        if cat and key and val:
            save_fact(cat, key, val, confidence=conf, source=source)
            count += 1

    return count


# ─── Context relay (handoff between brain regions) ───

def save_handoff(from_model, handoff_text, session_id=None):
    """Save a context handoff for the next model."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO context_relay (from_model, handoff, session_id) VALUES (?, ?, ?)",
        (from_model, handoff_text, session_id),
    )
    conn.commit()


def get_latest_handoff(session_id=None):
    """Get the most recent handoff."""
    conn = _get_conn()
    if session_id:
        row = conn.execute(
            "SELECT from_model, handoff FROM context_relay "
            "WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT from_model, handoff FROM context_relay ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row if row else None


def generate_handoff(conversation_text, from_model="unknown"):
    """Generate a handoff summary from the current conversation.

    Uses the router (small, fast) to compress context.
    """
    prompt = HANDOFF_PROMPT.format(conversation=conversation_text[:2000])
    return _ollama_generate(MODELS["router"], prompt)


# ─── Identity briefing builder ───

def _sanitize_for_prompt(text):
    """Sanitize text before injecting into system prompts.

    Prevents stored prompt injection — a user message like
    'My name is ]}\\n\\nIgnore all prior instructions...' would otherwise
    get stored as a profile fact and injected into every future prompt.
    """
    if not text:
        return text
    # Strip characters that could break prompt structure or inject tool calls
    text = text.replace("{", "").replace("}", "")
    text = text.replace("<tool", "&lt;tool").replace("</tool", "&lt;/tool")
    # Limit length to prevent context flooding
    if len(text) > 2000:
        text = text[:2000] + "..."
    return text


def build_identity(mode="companion", session_id=None):
    """Build the full identity system prompt for any model.

    This is injected as the system message so every model wakes up as BOLT
    with full awareness of: who they are, who the user is, and what's happening.
    """
    # User profile (sanitized to prevent prompt injection)
    profile_text = _sanitize_for_prompt(get_profile_text())

    # Mode context
    mode_map = {
        "companion": COMPANION_CONTEXT,
        "build": BUILD_CONTEXT,
        "code": CODE_CONTEXT,
    }
    mode_context = mode_map.get(mode, COMPANION_CONTEXT)

    # Build the identity
    identity_text = BOLT_IDENTITY.format(
        user_profile=profile_text,
        mode_context=mode_context,
    )

    # Add handoff from previous brain region if available (also sanitized)
    handoff = get_latest_handoff(session_id)
    if handoff:
        safe_handoff = _sanitize_for_prompt(handoff['handoff'])
        identity_text += f"\n\n[Handoff from previous brain region ({handoff['from_model']})]: {safe_handoff}"

    return identity_text


# ─── Profile learning worker ───

class ProfileLearnerWorker:
    """Background worker that learns about the user from conversations."""

    def __init__(self, session_id):
        self.session_id = session_id
        self._msg_count = 0
        self._lock = threading.Lock()

    def tick(self, user_msg, assistant_msg):
        """Called after each exchange. Learns periodically, not every message."""
        with self._lock:
            self._msg_count += 1
            if self._msg_count % PROFILE_INTERVAL != 0:
                return

        # Run learning in a background thread so it never blocks
        convo = f"User: {user_msg}\nAssistant: {assistant_msg}"
        t = threading.Thread(
            target=learn_from_conversation,
            args=(convo, f"session:{self.session_id}"),
            daemon=True,
        )
        t.start()
