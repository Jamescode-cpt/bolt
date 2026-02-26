"""
BOLT Custom Tool: env
Read-only environment variable inspector.
Redacts sensitive values (KEY, SECRET, TOKEN, PASSWORD in the name).
"""

import os

TOOL_NAME = "env"
TOOL_DESC = (
    "Read-only environment variable tool. "
    "Subcommands: list (show all, redacted), get <name>, path (show PATH entries)."
)

# Words in env var names that trigger redaction
_SENSITIVE = {"KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH"}


def _is_sensitive(name):
    """Return True if the variable name contains a sensitive keyword."""
    upper = name.upper()
    return any(kw in upper for kw in _SENSITIVE)


def run(args):
    """Dispatch to the requested subcommand."""
    try:
        parts = args.strip().split(None, 1) if args else []
        subcmd = parts[0].lower() if parts else "list"

        if subcmd == "list":
            return _cmd_list()
        elif subcmd == "get":
            if len(parts) < 2:
                return "Usage: env get <VARIABLE_NAME>"
            return _cmd_get(parts[1].strip())
        elif subcmd == "path":
            return _cmd_path()
        else:
            return (
                f"Unknown subcommand '{subcmd}'.\n"
                "Available: list, get <name>, path"
            )

    except Exception as e:
        return f"env tool error: {e}"


def _cmd_list():
    """List all env vars sorted alphabetically, redacting sensitive ones."""
    env = os.environ
    if not env:
        return "No environment variables found."

    lines = []
    for name in sorted(env.keys()):
        if _is_sensitive(name):
            lines.append(f"  {name} = [REDACTED]")
        else:
            lines.append(f"  {name} = {env[name]}")

    header = f"Environment variables ({len(lines)} total):\n"
    return header + "\n".join(lines)


def _cmd_get(name):
    """Get a single env var by name."""
    value = os.environ.get(name)
    if value is None:
        return f"'{name}' is not set."
    if _is_sensitive(name):
        return f"{name} = [REDACTED] (sensitive variable)"
    return f"{name} = {value}"


def _cmd_path():
    """Show PATH entries, one per line."""
    raw = os.environ.get("PATH", "")
    if not raw:
        return "PATH is empty or not set."

    entries = raw.split(os.pathsep)
    lines = [f"  {i+1}. {p}" for i, p in enumerate(entries)]
    return f"PATH ({len(entries)} entries):\n" + "\n".join(lines)
