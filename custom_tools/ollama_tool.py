"""BOLT custom tool — Ollama model management via REST API.

Manage local Ollama models: list, show, pull, remove, running/ps.
Uses requests library (already installed for BOLT).
Protects the always-on router model (qwen2.5:1.5b) from removal.
"""

TOOL_NAME = "ollama"
TOOL_DESC = (
    "Manage Ollama models via REST API. "
    'Usage: <tool name="ollama">list</tool> — list all models | '
    '<tool name="ollama">show qwen2.5:7b</tool> — model details | '
    '<tool name="ollama">pull qwen2.5:3b</tool> — download a model | '
    '<tool name="ollama">remove <model></tool> — remove a model (router protected) | '
    '<tool name="ollama">running</tool> or <tool name="ollama">ps</tool> — loaded models & VRAM'
)

OLLAMA_BASE = "http://localhost:11434"
PROTECTED_MODELS = {
    "qwen2.5:1.5b",              # router
    "qwen2.5:7b",                # companion
    "qwen2.5-coder:3b",          # fast_code
    "qwen2.5-coder:7b",          # worker_light
    "qwen2.5-coder:14b",         # worker_heavy
    "qwen2.5-coder:32b-instruct-q3_K_M",  # beast
}


def _human_size(nbytes):
    """Convert bytes to human-readable string."""
    if nbytes is None:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024.0:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f} PB"


def _human_duration(seconds):
    """Convert seconds to a human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _format_timestamp(ts_str):
    """Format an ISO timestamp to a shorter human-readable form."""
    if not ts_str:
        return "unknown"
    # Ollama returns ISO 8601 timestamps
    try:
        # Try to parse and simplify
        return ts_str[:19].replace("T", " ")
    except Exception:
        return str(ts_str)


def _api_get(path, timeout=15):
    """GET request to Ollama API. Returns (data_dict, error_string)."""
    try:
        import requests
    except ImportError:
        return None, "requests library not installed — run: pip install requests"

    url = f"{OLLAMA_BASE}{path}"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            return resp.json(), None
        else:
            return None, f"Ollama API error {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return None, f"Cannot reach Ollama at {OLLAMA_BASE} — {e}"


def _api_post(path, payload, timeout=30):
    """POST request to Ollama API. Returns (data_dict, error_string)."""
    try:
        import requests
    except ImportError:
        return None, "requests library not installed — run: pip install requests"

    url = f"{OLLAMA_BASE}{path}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code == 200:
            try:
                return resp.json(), None
            except Exception:
                return {"raw": resp.text[:500]}, None
        else:
            return None, f"Ollama API error {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return None, f"Cannot reach Ollama at {OLLAMA_BASE} — {e}"


def _api_delete(path, payload, timeout=30):
    """DELETE request to Ollama API. Returns (data_dict, error_string)."""
    try:
        import requests
    except ImportError:
        return None, "requests library not installed — run: pip install requests"

    url = f"{OLLAMA_BASE}{path}"
    try:
        resp = requests.delete(url, json=payload, timeout=timeout)
        if resp.status_code == 200:
            return {"status": "success"}, None
        else:
            return None, f"Ollama API error {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return None, f"Cannot reach Ollama at {OLLAMA_BASE} — {e}"


def _cmd_list():
    """List all downloaded models."""
    data, err = _api_get("/api/tags")
    if err:
        return err

    models = data.get("models", [])
    if not models:
        return "No models downloaded."

    lines = [f"{'Model':<35} {'Size':>10}   {'Modified'}"]
    lines.append("-" * 70)

    for m in sorted(models, key=lambda x: x.get("name", "")):
        name = m.get("name", "unknown")
        size = _human_size(m.get("size", 0))
        modified = _format_timestamp(m.get("modified_at", ""))
        lines.append(f"{name:<35} {size:>10}   {modified}")

    lines.append(f"\nTotal: {len(models)} model(s)")
    return "\n".join(lines)


def _cmd_show(model_name):
    """Show details for a specific model."""
    if not model_name:
        return "Usage: show <model_name>\nExample: show qwen2.5:7b"

    data, err = _api_post("/api/show", {"name": model_name})
    if err:
        return err

    lines = [f"Model: {model_name}", ""]

    # Parameters
    params = data.get("parameters", "")
    if params:
        lines.append("Parameters:")
        for line in params.strip().splitlines():
            lines.append(f"  {line.strip()}")
        lines.append("")

    # Template (truncated)
    template = data.get("template", "")
    if template:
        preview = template[:300]
        if len(template) > 300:
            preview += "... (truncated)"
        lines.append(f"Template:\n  {preview}")
        lines.append("")

    # Model info
    details = data.get("details", {})
    if details:
        lines.append("Details:")
        for k, v in details.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    # License (truncated)
    license_text = data.get("license", "")
    if license_text:
        preview = license_text[:200]
        if len(license_text) > 200:
            preview += "... (truncated)"
        lines.append(f"License:\n  {preview}")

    return "\n".join(lines)


def _cmd_pull(model_name):
    """Start pulling a model (non-blocking status check)."""
    if not model_name:
        return "Usage: pull <model_name>\nExample: pull qwen2.5:3b"

    # Use stream=false for a simple status response
    # But Ollama pull can take a long time, so we do a non-blocking start
    try:
        import requests
    except ImportError:
        return "requests library not installed — run: pip install requests"

    url = f"{OLLAMA_BASE}/api/pull"
    try:
        # Send with stream=True to get incremental status, but only read first few chunks
        resp = requests.post(
            url,
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=30,
        )
        if resp.status_code != 200:
            return f"Pull failed: HTTP {resp.status_code} — {resp.text[:200]}"

        # Read first few status lines to confirm it started
        import json as json_mod
        status_lines = []
        count = 0
        for line in resp.iter_lines():
            if not line:
                continue
            count += 1
            try:
                chunk = json_mod.loads(line)
                status = chunk.get("status", "")
                status_lines.append(status)
                # If we see "success", it was already downloaded
                if status == "success":
                    resp.close()
                    return f"Model '{model_name}' is already up to date."
            except Exception:
                status_lines.append(line.decode("utf-8", errors="replace")[:100])
            if count >= 5:
                break

        resp.close()
        return (
            f"Pull started for '{model_name}'.\n"
            f"Initial status: {'; '.join(status_lines)}\n"
            f"The download continues in the background on the Ollama server.\n"
            f"Use 'list' to check when it appears."
        )
    except Exception as e:
        return f"Pull error: {e}"


def _cmd_remove(model_name):
    """Remove a model (with router protection)."""
    if not model_name:
        return "Usage: remove <model_name>\nExample: remove llama3:8b"

    # Protect all BOLT roster models from removal
    clean_name = model_name.strip().lower()
    for protected in PROTECTED_MODELS:
        if clean_name == protected.lower():
            return (
                f"BLOCKED: '{model_name}' is a BOLT roster model and cannot be removed.\n"
                f"Protected models: {', '.join(sorted(PROTECTED_MODELS))}"
            )

    data, err = _api_delete("/api/delete", {"name": model_name})
    if err:
        return f"Remove failed: {err}"

    return f"Model '{model_name}' removed successfully."


def _cmd_running():
    """Show currently loaded/running models."""
    data, err = _api_get("/api/ps")
    if err:
        return err

    models = data.get("models", [])
    if not models:
        return "No models currently loaded in memory."

    lines = [f"{'Model':<35} {'Size':>10}   {'VRAM':>10}   {'Until'}"]
    lines.append("-" * 80)

    for m in models:
        name = m.get("name", "unknown")
        size = _human_size(m.get("size", 0))
        vram = _human_size(m.get("size_vram", 0))
        expires = m.get("expires_at", "")
        expires_short = _format_timestamp(expires)
        lines.append(f"{name:<35} {size:>10}   {vram:>10}   {expires_short}")

    lines.append(f"\nLoaded: {len(models)} model(s)")
    return "\n".join(lines)


def run(args):
    """Manage Ollama models. Args: list | show <model> | pull <model> | remove <model> | running | ps"""
    raw = args.strip() if args else ""

    if not raw:
        return (
            "Ollama model manager. Commands:\n"
            "  list              — list all downloaded models\n"
            "  show <model>      — show model details\n"
            "  pull <model>      — download a model\n"
            "  remove <model>    — remove a model (router protected)\n"
            "  running / ps      — show loaded models & VRAM"
        )

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd == "list":
            return _cmd_list()
        elif cmd == "show":
            return _cmd_show(rest)
        elif cmd == "pull":
            return _cmd_pull(rest)
        elif cmd == "remove" or cmd == "delete" or cmd == "rm":
            return _cmd_remove(rest)
        elif cmd in ("running", "ps", "loaded"):
            return _cmd_running()
        else:
            return (
                f"Unknown command: {cmd}\n"
                "Valid commands: list, show, pull, remove, running, ps"
            )
    except Exception as e:
        return f"ollama tool error: {e}"
