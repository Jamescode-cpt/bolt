"""BOLT cloud brain — provider-agnostic LLM integration.

Supports any OpenAI-compatible provider (OpenAI, Groq, Mistral, Together,
OpenRouter, DeepSeek, etc.) plus Anthropic's native format. Auto-detects
the provider from the API key prefix. No new dependencies — just requests.

Env vars:
  BOLT_CLOUD_KEY   — any provider's API key (required)
  BOLT_CLOUD_MODEL — override model name (optional, auto-defaults per provider)
  BOLT_CLOUD_URL   — override API endpoint (optional, auto-detected from key)

Backward compat: ANTHROPIC_API_KEY works if BOLT_CLOUD_KEY isn't set.
"""

import json
import os
import time
import requests

# ─── Provider auto-detection table ───
# Order matters in _PREFIX_ORDER — check longer prefixes first so
# "sk-ant-" matches before the shorter "sk-" catch-all.

_PROVIDERS = {
    "sk-ant-": {
        "name": "Anthropic",
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-6",
        "format": "anthropic",
    },
    "sk-or-": {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "anthropic/claude-sonnet-4-6",
        "format": "openai",
    },
    "gsk_": {
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.3-70b-versatile",
        "format": "openai",
    },
    "sk-": {
        "name": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o",
        "format": "openai",
    },
}

_PREFIX_ORDER = ["sk-ant-", "sk-or-", "gsk_", "sk-"]

ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 8192

# ─── Config resolution (lazy, so env vars can be set after import) ───

_config = None


def _resolve_config():
    """Read env vars, auto-detect provider. Returns dict or None."""
    key = os.environ.get("BOLT_CLOUD_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None

    url_override = os.environ.get("BOLT_CLOUD_URL")
    model_override = os.environ.get("BOLT_CLOUD_MODEL")

    # Auto-detect from key prefix
    provider = None
    for prefix in _PREFIX_ORDER:
        if key.startswith(prefix):
            provider = dict(_PROVIDERS[prefix])
            break

    if provider is None:
        # Unknown key prefix — need explicit URL
        if not url_override:
            return None
        provider = {
            "name": "Custom",
            "url": url_override,
            "model": model_override or "unknown",
            "format": "openai",
        }

    # Apply overrides
    if url_override:
        provider["url"] = url_override
    if model_override:
        provider["model"] = model_override

    # Format detection: if URL contains "anthropic" → anthropic format
    if "anthropic" in provider["url"]:
        provider["format"] = "anthropic"

    provider["key"] = key
    return provider


def _get_config():
    """Lazy-load config."""
    global _config
    if _config is None:
        _config = _resolve_config()
    return _config


# ─── Availability cache ───

_available_cache = {"result": None, "checked_at": 0}
_CACHE_TTL = 60


def _ping():
    """Quick connectivity check. Works for both API formats."""
    cfg = _get_config()
    if not cfg:
        return False
    try:
        if cfg["format"] == "anthropic":
            resp = requests.get(
                cfg["url"],
                headers={"x-api-key": cfg["key"]},
                timeout=5,
            )
        else:
            resp = requests.get(
                cfg["url"],
                headers={"Authorization": f"Bearer {cfg['key']}"},
                timeout=5,
            )
        # Any HTTP response means the server is reachable
        return resp.status_code in (200, 401, 403, 404, 405)
    except Exception:
        return False


def is_available():
    """True if API key exists AND cloud API is reachable. Cached for 60s."""
    cfg = _get_config()
    if not cfg:
        return False

    now = time.time()
    if now - _available_cache["checked_at"] < _CACHE_TTL and _available_cache["result"] is not None:
        return _available_cache["result"]

    result = _ping()
    _available_cache["result"] = result
    _available_cache["checked_at"] = now
    return result


def get_display_name():
    """Return 'model @ Provider' for the banner. Empty string if no cloud."""
    cfg = _get_config()
    if not cfg:
        return ""
    return f"{cfg['model']} @ {cfg['name']}"


# ─── Chat interface (preserved: same signature brain.py expects) ───

def chat(messages, stream_callback=None):
    """Send messages to cloud LLM. Yields text chunks.

    Routes to Anthropic or OpenAI-compatible format based on auto-detection.
    Same interface regardless of provider — both yield plain text chunks.
    """
    cfg = _get_config()
    if not cfg:
        yield "[BOLT: Cloud brain unavailable — no API key set.]"
        return

    if cfg["format"] == "anthropic":
        yield from _chat_anthropic(cfg, messages)
    else:
        yield from _chat_openai(cfg, messages)


# ─── Anthropic native format ───

def _chat_anthropic(cfg, messages):
    """Anthropic SSE: content_block_delta → delta.text_delta.text"""
    system_parts = []
    chat_messages = []

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if not content or not content.strip():
            continue
        if role == "system":
            system_parts.append(content)
        else:
            if role not in ("user", "assistant"):
                role = "user"
            if chat_messages and chat_messages[-1]["role"] == role:
                chat_messages[-1]["content"] += "\n" + content
            else:
                chat_messages.append({"role": role, "content": content})

    if not chat_messages:
        yield "[BOLT: No messages to send.]"
        return

    if chat_messages[0]["role"] != "user":
        chat_messages.insert(0, {"role": "user", "content": "(continuing conversation)"})

    system_text = "\n\n".join(system_parts) if system_parts else None

    headers = {
        "x-api-key": cfg["key"],
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    payload = {
        "model": cfg["model"],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "messages": chat_messages,
    }
    if system_text:
        payload["system"] = system_text

    try:
        resp = requests.post(cfg["url"], headers=headers, json=payload, stream=True, timeout=300)
    except requests.ConnectionError:
        _available_cache["result"] = None
        yield "[BOLT: Can't reach cloud brain — we're local now.]"
        return
    except requests.Timeout:
        yield "[BOLT: Cloud brain timed out — we're local now.]"
        return
    except Exception as e:
        yield f"[BOLT: Cloud connection error — {e}]"
        return

    if resp.status_code != 200:
        try:
            err = resp.json()
            err_msg = err.get("error", {}).get("message", resp.text[:200])
        except Exception:
            err_msg = f"HTTP {resp.status_code}"
        yield f"[BOLT: Cloud error — {err_msg}]"
        return

    partial = ""
    try:
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8") if isinstance(line, bytes) else line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type", "")
            if event_type == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        partial += text
                        yield text
            elif event_type == "message_stop":
                break
            elif event_type == "error":
                err_msg = data.get("error", {}).get("message", "unknown error")
                if partial:
                    yield f"\n[connection lost — {err_msg}]"
                else:
                    yield f"[BOLT: Cloud error — {err_msg}]"
                break

    except requests.exceptions.ChunkedEncodingError:
        if partial:
            yield "\n[connection lost, switching to local]"
        else:
            yield "[BOLT: Cloud connection dropped — we're local now.]"
        _available_cache["result"] = None
    except Exception as e:
        if partial:
            yield f"\n[connection lost — {e}]"
        else:
            yield f"[BOLT: Cloud error — {e}]"


# ─── OpenAI-compatible format ───

def _chat_openai(cfg, messages):
    """OpenAI-compat SSE: choices[0].delta.content"""
    clean = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if not content or not content.strip():
            continue
        if role not in ("system", "user", "assistant"):
            role = "user"
        if clean and clean[-1]["role"] == role and role != "system":
            clean[-1]["content"] += "\n" + content
        else:
            clean.append({"role": role, "content": content})

    if not clean:
        yield "[BOLT: No messages to send.]"
        return

    headers = {
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": cfg["model"],
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "messages": clean,
    }

    try:
        resp = requests.post(cfg["url"], headers=headers, json=payload, stream=True, timeout=300)
    except requests.ConnectionError:
        _available_cache["result"] = None
        yield "[BOLT: Can't reach cloud brain — we're local now.]"
        return
    except requests.Timeout:
        yield "[BOLT: Cloud brain timed out — we're local now.]"
        return
    except Exception as e:
        yield f"[BOLT: Cloud connection error — {e}]"
        return

    if resp.status_code != 200:
        try:
            err = resp.json()
            err_msg = err.get("error", {}).get("message", resp.text[:200])
        except Exception:
            err_msg = f"HTTP {resp.status_code}"
        yield f"[BOLT: Cloud error — {err_msg}]"
        return

    partial = ""
    try:
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8") if isinstance(line, bytes) else line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                text = delta.get("content", "")
                if text:
                    partial += text
                    yield text
                if choices[0].get("finish_reason"):
                    break

    except requests.exceptions.ChunkedEncodingError:
        if partial:
            yield "\n[connection lost, switching to local]"
        else:
            yield "[BOLT: Cloud connection dropped — we're local now.]"
        _available_cache["result"] = None
    except Exception as e:
        if partial:
            yield f"\n[connection lost — {e}]"
        else:
            yield f"[BOLT: Cloud error — {e}]"
