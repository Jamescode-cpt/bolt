"""BOLT custom tool — manage user crontab.

List, add, remove cron entries. User crontab only (no sudo).
Command paths validated: only ~/ scripts + system binaries allowed.
"""

import os
import re
import shutil
import subprocess

TOOL_NAME = "cron"
TOOL_DESC = (
    "Manage user crontab entries. "
    'Usage: <tool name="cron">list</tool> or '
    '<tool name="cron">add * * * * * /home/mobilenode/script.sh</tool> or '
    '<tool name="cron">remove 3</tool> (removes line 3)'
)

HOME = os.path.expanduser("~")

# Allowed command prefixes — home dir scripts + common system binaries
ALLOWED_CMD_PREFIXES = [
    HOME + "/",
    "/usr/bin/",
    "/usr/local/bin/",
    "/bin/",
]

# Dangerous patterns to block
BLOCKED_PATTERNS = [
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"\bdd\s+", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\breboot\b", re.IGNORECASE),
]

# Cron schedule: 5 fields (min hour dom mon dow) — basic validation
CRON_SCHEDULE_RE = re.compile(
    r"^(\S+\s+){4}\S+"  # 5 space-separated fields
)


def _get_crontab():
    """Get current user crontab as list of lines."""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            if "no crontab" in (result.stderr or "").lower():
                return []
            return None
        return result.stdout.strip().splitlines() if result.stdout.strip() else []
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _set_crontab(lines):
    """Write crontab from list of lines."""
    content = "\n".join(lines) + "\n" if lines else ""
    try:
        result = subprocess.run(
            ["crontab", "-"],
            input=content, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return f"crontab write failed: {result.stderr.strip()}"
        return None  # success
    except Exception as e:
        return f"crontab error: {e}"


def _validate_command(cmd_part):
    """Validate the command part of a cron entry."""
    cmd_part = cmd_part.strip()

    # Block pipe and command substitution
    if any(c in cmd_part for c in ['|', '$(', '`']):
        return "Blocked: pipe and command substitution not allowed in cron commands."

    # Block dangerous patterns
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(cmd_part):
            return f"Blocked: dangerous pattern detected in command."

    # Extract the actual binary/script path (first word of the command)
    first_word = cmd_part.split()[0] if cmd_part.split() else ""

    # Expand ~ and resolve
    expanded = os.path.expanduser(first_word)

    # Check against allowed prefixes
    for prefix in ALLOWED_CMD_PREFIXES:
        if expanded.startswith(prefix):
            return None  # OK

    # For bare commands, resolve to full path and validate
    if "/" not in first_word:
        resolved = shutil.which(first_word)
        if resolved and not any(resolved.startswith(p) for p in ALLOWED_CMD_PREFIXES):
            return f"Command not in allowed path: {first_word} -> {resolved}"
        return None  # OK — either resolves to allowed path or not found (cron will handle)

    return (
        f"Blocked: command path '{first_word}' not under allowed directories.\n"
        f"Allowed: {HOME}/, /usr/bin/, /usr/local/bin/, /bin/"
    )


def _list():
    """List current crontab entries."""
    lines = _get_crontab()
    if lines is None:
        return "crontab not available (is cron installed?)"
    if not lines:
        return "No crontab entries."

    result = []
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            result.append(f"  {i}: {line}  (comment)")
        elif line.strip():
            result.append(f"  {i}: {line}")
    return "Current crontab:\n" + "\n".join(result)


def _add(entry):
    """Add a cron entry."""
    entry = entry.strip()
    if not entry:
        return "No cron entry provided."

    # Basic schedule validation
    if not CRON_SCHEDULE_RE.match(entry):
        return (
            "Invalid cron format. Expected: MIN HOUR DOM MON DOW command\n"
            "Example: */5 * * * * /home/mobilenode/script.sh"
        )

    # Extract command part (everything after the 5 schedule fields)
    parts = entry.split(None, 5)
    if len(parts) < 6:
        return "No command found after cron schedule fields."

    cmd_part = parts[5]
    err = _validate_command(cmd_part)
    if err:
        return err

    lines = _get_crontab()
    if lines is None:
        return "crontab not available."

    lines.append(entry)
    err = _set_crontab(lines)
    if err:
        return err
    return f"Added cron entry: {entry}\nTotal entries: {len(lines)}"


def _remove(line_num_str):
    """Remove a cron entry by line number."""
    try:
        line_num = int(line_num_str.strip())
    except ValueError:
        return f"Invalid line number: {line_num_str}"

    lines = _get_crontab()
    if lines is None:
        return "crontab not available."
    if not lines:
        return "Crontab is empty."
    if line_num < 1 or line_num > len(lines):
        return f"Invalid line number: {line_num}. Crontab has {len(lines)} entries."

    removed = lines.pop(line_num - 1)
    err = _set_crontab(lines)
    if err:
        return err
    return f"Removed line {line_num}: {removed}\nRemaining entries: {len(lines)}"


def run(args):
    """Manage user crontab.

    Args: 'list', 'add <cron entry>', or 'remove <line number>'.
    """
    raw = args.strip() if args else ""
    if not raw:
        return (
            'Usage:\n'
            '  <tool name="cron">list</tool>\n'
            '  <tool name="cron">add */5 * * * * /home/mobilenode/script.sh</tool>\n'
            '  <tool name="cron">remove 3</tool>'
        )

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd == "list" or cmd == "ls":
            return _list()
        elif cmd == "add":
            return _add(arg)
        elif cmd == "remove" or cmd == "rm" or cmd == "delete":
            return _remove(arg)
        else:
            return f"Unknown subcommand: {cmd}. Available: list, add, remove"
    except Exception as e:
        return f"cron error: {e}"
