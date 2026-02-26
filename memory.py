"""Shared persistent memory layer — SQLite backed."""

import sqlite3
import os
import threading
from config import MAX_CONTEXT_TOKENS, CHARS_PER_TOKEN

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bolt.db")

_local = threading.local()


def _get_conn():
    """Thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            ts DATETIME DEFAULT (datetime('now')),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            token_estimate INTEGER
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            ts DATETIME DEFAULT (datetime('now')),
            summary TEXT NOT NULL,
            covers_up_to INTEGER,
            token_estimate INTEGER
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME DEFAULT (datetime('now')),
            updated_at DATETIME DEFAULT (datetime('now')),
            title TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            context_json TEXT
        );

        CREATE TABLE IF NOT EXISTS timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT (datetime('now')),
            event TEXT NOT NULL,
            details TEXT
        );

        CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS session_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            started_at DATETIME,
            ended_at DATETIME DEFAULT (datetime('now')),
            message_count INTEGER DEFAULT 0,
            summary TEXT,
            context TEXT
        );
    """)
    conn.commit()


def estimate_tokens(text):
    """Rough token estimate."""
    return max(1, len(text) // CHARS_PER_TOKEN)


# --- Message operations ---

def save_message(session_id, role, content):
    """Store a message and return its id."""
    conn = _get_conn()
    tokens = estimate_tokens(content)
    cur = conn.execute(
        "INSERT INTO messages (session_id, role, content, token_estimate) VALUES (?, ?, ?, ?)",
        (session_id, role, content, tokens),
    )
    conn.commit()
    return cur.lastrowid


def get_recent_messages(session_id, limit=50):
    """Get the most recent messages for a session."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, content, token_estimate FROM messages "
        "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return list(reversed(rows))


def count_unsummarized(session_id):
    """Count messages since last summary."""
    conn = _get_conn()
    last = conn.execute(
        "SELECT covers_up_to FROM summaries WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    after_id = last["covers_up_to"] if last else 0
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ? AND id > ?",
        (session_id, after_id),
    ).fetchone()
    return row["cnt"]


def get_unsummarized_messages(session_id):
    """Get messages not yet covered by a summary."""
    conn = _get_conn()
    last = conn.execute(
        "SELECT covers_up_to FROM summaries WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    after_id = last["covers_up_to"] if last else 0
    rows = conn.execute(
        "SELECT id, role, content FROM messages WHERE session_id = ? AND id > ? ORDER BY id",
        (session_id, after_id),
    ).fetchall()
    return list(rows)


def get_latest_message_id(session_id):
    """Get the id of the most recent message."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT MAX(id) as mid FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row["mid"] if row else 0


# --- Summary operations ---

def save_summary(session_id, summary_text, covers_up_to):
    conn = _get_conn()
    tokens = estimate_tokens(summary_text)
    conn.execute(
        "INSERT INTO summaries (session_id, summary, covers_up_to, token_estimate) VALUES (?, ?, ?, ?)",
        (session_id, summary_text, covers_up_to, tokens),
    )
    conn.commit()


def get_latest_summary(session_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT summary, covers_up_to FROM summaries WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return row if row else None


# --- Task operations ---

def upsert_task(title, status="active", context_json=None):
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM tasks WHERE status = 'active' LIMIT 1"
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE tasks SET title=?, status=?, context_json=?, updated_at=datetime('now') WHERE id=?",
            (title, status, context_json, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO tasks (title, status, context_json) VALUES (?, ?, ?)",
            (title, status, context_json),
        )
    conn.commit()


def get_active_task():
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, title, status, context_json FROM tasks WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    return row


def complete_active_task():
    conn = _get_conn()
    conn.execute("UPDATE tasks SET status='done', updated_at=datetime('now') WHERE status='active'")
    conn.commit()


def get_all_tasks(limit=20):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, title, status, created_at, updated_at FROM tasks ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return list(rows)


# --- Timeline ---

def log_event(event, details=None):
    conn = _get_conn()
    conn.execute("INSERT INTO timeline (event, details) VALUES (?, ?)", (event, details))
    conn.commit()


def get_timeline(limit=30):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT ts, event, details FROM timeline ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return list(reversed(rows))


# --- KV state ---

def kv_set(key, value):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO kv (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value),
    )
    conn.commit()


def kv_get(key, default=None):
    conn = _get_conn()
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


# --- Session snapshots ---

def save_session_snapshot(session_id):
    """Compact and save a session snapshot on shutdown.

    Stores: when it started, when it ended, message count, latest summary,
    and a compressed context of the last few exchanges.
    """
    conn = _get_conn()

    # Get message count and first message timestamp
    row = conn.execute(
        "SELECT COUNT(*) as cnt, MIN(ts) as first_ts FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    msg_count = row["cnt"] if row else 0

    if msg_count == 0:
        return  # Nothing to snapshot

    started_at = row["first_ts"]

    # Get latest summary
    summary_row = get_latest_summary(session_id)
    summary = summary_row["summary"] if summary_row else None

    # Build compact context from last few exchanges
    recent = get_recent_messages(session_id, limit=20)
    context_parts = []
    for r in recent:
        role = r["role"]
        if role in ("tool", "tool_result"):
            continue
        content = r["content"]
        if len(content) > 200:
            content = content[:200] + "..."
        context_parts.append(f"{role}: {content}")
    context = "\n".join(context_parts) if context_parts else None

    # Upsert snapshot
    conn.execute(
        """INSERT INTO session_snapshots (session_id, started_at, message_count, summary, context)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
               ended_at=datetime('now'),
               message_count=excluded.message_count,
               summary=COALESCE(excluded.summary, session_snapshots.summary),
               context=excluded.context""",
        (session_id, started_at, msg_count, summary, context),
    )
    conn.commit()


def get_session_snapshots(limit=10):
    """Get recent session snapshots for recall."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT session_id, started_at, ended_at, message_count, summary, context "
        "FROM session_snapshots ORDER BY ended_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return list(rows)


def get_session_snapshot(session_id):
    """Get a specific session snapshot."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT session_id, started_at, ended_at, message_count, summary, context "
        "FROM session_snapshots WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row


# --- Context builder (the memory relay) ---

def build_context(session_id, system_prompt=""):
    """Build context payload for a model call (without identity — use brain for full context).

    Returns a list of {role, content} dicts ready for the Ollama messages API.
    """
    budget = MAX_CONTEXT_TOKENS
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
        budget -= estimate_tokens(system_prompt)

    # Latest summary
    summary = get_latest_summary(session_id)
    if summary:
        summary_text = f"[Conversation summary so far]: {summary['summary']}"
        cost = estimate_tokens(summary_text)
        if cost < budget:
            messages.append({"role": "system", "content": summary_text})
            budget -= cost

    # Active task
    task = get_active_task()
    if task:
        task_text = f"[Current task]: {task['title']} (status: {task['status']})"
        cost = estimate_tokens(task_text)
        if cost < budget:
            messages.append({"role": "system", "content": task_text})
            budget -= cost

    # Recent messages that fit
    recent = get_recent_messages(session_id)
    selected = []
    total_cost = 0
    for row in reversed(recent):
        cost = row["token_estimate"] or estimate_tokens(row["content"])
        if total_cost + cost > budget:
            break
        selected.append(row)
        total_cost += cost
    selected.reverse()

    for row in selected:
        role = row["role"]
        if role in ("tool", "tool_result"):
            role = "system"
        elif role not in ("user", "assistant", "system"):
            role = "user"
        messages.append({"role": role, "content": row["content"]})

    return messages
