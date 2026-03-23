"""BOLT custom tool — desktop notifications.

Cross-platform: Linux (notify-send), macOS (osascript).
Supports body-only, title+body, or urgency+title+body.
500 char cap per field.
"""

import os
import sys

TOOL_NAME = "notify"
TOOL_DESC = (
    "Send a desktop notification. "
    'Usage: <tool name="notify">message</tool> or '
    '<tool name="notify">title\nbody</tool> or '
    '<tool name="notify">urgency\ntitle\nbody</tool> (urgency: low/normal/critical)'
)

MAX_FIELD_LEN = 500

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import send_notification


def _truncate(text, limit=MAX_FIELD_LEN):
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def run(args):
    """Send a desktop notification."""
    raw = args.strip() if args else ""
    if not raw:
        return "No message provided. Usage: <tool name=\"notify\">your message</tool>"

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
        success, message = send_notification(title, body, urgency)
        return message
    except Exception as e:
        return f"notify error: {e}"
