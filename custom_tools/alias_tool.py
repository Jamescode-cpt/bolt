"""
BOLT Custom Tool: alias
Save, list, run, and remove command aliases.
Persisted to ~/bolt/aliases.json.

Safety:
  - Commands can only reference paths under /home/mobilenode/ or standard
    system binaries (/usr/bin, /usr/sbin, /bin, /sbin, /usr/local/bin).
  - No sudo allowed in alias commands.
  - Subprocess runs with a timeout (30s default).
"""

import json
import os
import subprocess
import shlex
import re

TOOL_NAME = "alias"
TOOL_DESC = (
    "Command alias manager. "
    "Subcommands: add <name> <command>, list, run <name>, remove <name>."
)

_ALIASES_PATH = os.path.expanduser("~/bolt/aliases.json")
_RUN_TIMEOUT = 30  # seconds

# Allowed path prefixes for commands/arguments that look like paths
_ALLOWED_PATH_PREFIXES = (
    "/home/mobilenode/",
    "/usr/bin/",
    "/usr/sbin/",
    "/usr/local/bin/",
    "/bin/",
    "/sbin/",
)

# Patterns that are never allowed in alias commands
_BLOCKED_PATTERNS = [
    r"\bsudo\b",
    r"\brm\s+-rf\s+/",       # rm -rf /
    r"\bmkfs\b",
    r"\bdd\b.*\bof=/dev/",
    r">\s*/dev/sd",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+[06]\b",
]


def _load():
    """Load aliases from disk."""
    try:
        if os.path.exists(_ALIASES_PATH):
            with open(_ALIASES_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, IOError, OSError):
        pass
    return {}


def _save(aliases):
    """Write aliases to disk."""
    parent = os.path.dirname(_ALIASES_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(_ALIASES_PATH, "w") as f:
        json.dump(aliases, f, indent=2)


def _validate_command(command):
    """
    Check the command against safety rules.
    Returns (ok: bool, reason: str).
    """
    # Block dangerous patterns
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return False, f"Blocked pattern detected: {pattern}"

    # Check that any absolute paths referenced are within allowed prefixes
    # Extract tokens that look like absolute paths
    tokens = command.split()
    for token in tokens:
        if token.startswith("/"):
            # Resolve to catch ../ tricks
            resolved = os.path.realpath(token)
            if not any(resolved.startswith(prefix.rstrip("/")) for prefix in _ALLOWED_PATH_PREFIXES):
                return False, (
                    f"Path '{token}' (resolves to '{resolved}') is outside allowed directories. "
                    f"Allowed: {', '.join(_ALLOWED_PATH_PREFIXES)}"
                )

    return True, ""


def run(args):
    """Dispatch subcommand."""
    try:
        parts = args.strip().split(None, 1) if args else []
        subcmd = parts[0].lower() if parts else "list"

        if subcmd == "add":
            return _cmd_add(parts[1].strip() if len(parts) > 1 else "")
        elif subcmd == "list":
            return _cmd_list()
        elif subcmd == "run":
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: alias run <name>"
            return _cmd_run(parts[1].strip())
        elif subcmd == "remove":
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: alias remove <name>"
            return _cmd_remove(parts[1].strip())
        else:
            return (
                f"Unknown subcommand '{subcmd}'.\n"
                "Available: add <name> <command>, list, run <name>, remove <name>"
            )

    except Exception as e:
        return f"alias tool error: {e}"


def _cmd_add(raw):
    """Add a new alias.  Format: <name> <command...>"""
    parts = raw.split(None, 1)
    if len(parts) < 2:
        return "Usage: alias add <name> <command>\nExample: alias add status git status"

    name = parts[0]
    command = parts[1]

    # Validate name (alphanumeric + underscore/dash)
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return f"Invalid alias name '{name}'. Use only letters, numbers, underscores, dashes."

    # Safety check
    ok, reason = _validate_command(command)
    if not ok:
        return f"Command rejected: {reason}"

    aliases = _load()
    overwrite = name in aliases
    aliases[name] = command
    _save(aliases)

    action = "Updated" if overwrite else "Added"
    return f"{action} alias '{name}' -> {command}"


def _cmd_list():
    """Show all saved aliases."""
    aliases = _load()
    if not aliases:
        return "No aliases saved. Use 'alias add <name> <command>' to create one."

    lines = [f"Saved aliases ({len(aliases)}):"]
    for name in sorted(aliases.keys()):
        lines.append(f"  {name}  ->  {aliases[name]}")
    return "\n".join(lines)


def _cmd_run(name):
    """Execute a saved alias."""
    aliases = _load()
    if name not in aliases:
        return f"No alias named '{name}'. Use 'alias list' to see available aliases."

    command = aliases[name]

    # Re-validate before execution (file could have been hand-edited)
    ok, reason = _validate_command(command)
    if not ok:
        return f"Alias '{name}' blocked at runtime: {reason}"

    try:
        cmd_parts = shlex.split(command)
        result = subprocess.run(
            cmd_parts,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_RUN_TIMEOUT,
            cwd=os.path.expanduser("~"),
        )

        output_parts = []
        output_parts.append(f"[alias '{name}'] $ {command}")
        output_parts.append(f"Exit code: {result.returncode}")
        if result.stdout.strip():
            # Cap output to avoid flooding context
            stdout = result.stdout.strip()
            if len(stdout) > 4000:
                stdout = stdout[:4000] + "\n... (truncated)"
            output_parts.append(f"stdout:\n{stdout}")
        if result.stderr.strip():
            stderr = result.stderr.strip()
            if len(stderr) > 2000:
                stderr = stderr[:2000] + "\n... (truncated)"
            output_parts.append(f"stderr:\n{stderr}")

        return "\n".join(output_parts)

    except subprocess.TimeoutExpired:
        return f"Alias '{name}' timed out after {_RUN_TIMEOUT}s."
    except Exception as e:
        return f"Error running alias '{name}': {e}"


def _cmd_remove(name):
    """Delete an alias."""
    aliases = _load()
    if name not in aliases:
        return f"No alias named '{name}'."

    removed_cmd = aliases.pop(name)
    _save(aliases)
    return f"Removed alias '{name}' (was: {removed_cmd})"
