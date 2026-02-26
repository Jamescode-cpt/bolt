"""BOLT custom tool — desktop notifications via notify-send.

Wraps notify-send for easy desktop notifications.
Supports body-only, title+body, or urgency+title+body.
500 char cap per field.
"""

import subprocess
import shutil

TOOL_NAME = "notify"
TOOL_DESC = (
    "Send a desktop notification. "
    'Usage: <tool name="notify">message</tool> or '
    '<tool name="notify">title\nbody</tool> or '
    '<tool name="notify">urgency\ntitle\nbody</tool> (urgency: low/normal/critical)'
)

MAX_FIELD_LEN = 500


def _truncate(text, limit=MAX_FIELD_LEN):
    """Truncate text to limit."""
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def run(args):
    """Send a desktop notification.

    Args formats:
      - 'body' — notification with just a body
      - 'title\\nbody' — notification with title and body
      - 'urgency\\ntitle\\nbody' — with urgency level (low/normal/critical)
    """
    raw = args.strip() if args else ""
    if not raw:
        return "No message provided. Usage: <tool name=\"notify\">your message</tool>"

    if not shutil.which("notify-send"):
        return (
            "notify-send not found. Install with:\n"
            "  sudo apt install libnotify-bin    # Debian/Ubuntu\n"
            "  sudo pacman -S libnotify          # Arch/SteamOS"
        )

    lines = raw.split("\n", 2)
    urgency = "normal"
    title = "BOLT"
    body = ""

    if len(lines) == 1:
        body = _truncate(lines[0])
    elif len(lines) == 2:
        title = _truncate(lines[0])
        body = _truncate(lines[1])
    else:
        urg = lines[0].strip().lower()
        if urg in ("low", "normal", "critical"):
            urgency = urg
            title = _truncate(lines[1])
            body = _truncate(lines[2])
        else:
            title = _truncate(lines[0])
            body = _truncate(lines[1] + "\n" + lines[2])

    try:
        cmd = ["notify-send", "-u", urgency, title, body]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            err = result.stderr.strip() if result.stderr else "unknown error"
            return f"notify-send failed: {err}"
        return f"Notification sent: [{urgency}] {title}"
    except subprocess.TimeoutExpired:
        return "notify-send timed out"
    except Exception as e:
        return f"notify error: {e}"
