"""
BOLT Custom Tool: remind
Persistent reminder notes stored in ~/bolt/reminders.json.
Different from a timer — these are sticky notes BOLT can see in context.
"""

import json
import os
import datetime

TOOL_NAME = "remind"
TOOL_DESC = (
    "Persistent reminders. "
    "Subcommands: add <message>, list, done <id>, clear (remove completed)."
)

_REMINDERS_PATH = os.path.expanduser("~/bolt/reminders.json")


def _load():
    """Load reminders from disk. Returns a list of dicts."""
    try:
        if os.path.exists(_REMINDERS_PATH):
            with open(_REMINDERS_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, IOError, OSError) as e:
        # Corrupted file — start fresh but warn
        return []
    return []


def _save(reminders):
    """Write reminders to disk."""
    # Ensure parent dir exists
    parent = os.path.dirname(_REMINDERS_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(_REMINDERS_PATH, "w") as f:
        json.dump(reminders, f, indent=2)


def _next_id(reminders):
    """Return the next available integer id."""
    if not reminders:
        return 1
    return max(r.get("id", 0) for r in reminders) + 1


def run(args):
    """Dispatch subcommand."""
    try:
        parts = args.strip().split(None, 1) if args else []
        subcmd = parts[0].lower() if parts else "list"

        if subcmd == "add":
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: remind add <message>"
            return _cmd_add(parts[1].strip())
        elif subcmd == "list":
            return _cmd_list()
        elif subcmd == "done":
            if len(parts) < 2:
                return "Usage: remind done <id>"
            return _cmd_done(parts[1].strip())
        elif subcmd == "clear":
            return _cmd_clear()
        else:
            return (
                f"Unknown subcommand '{subcmd}'.\n"
                "Available: add <message>, list, done <id>, clear"
            )

    except Exception as e:
        return f"remind tool error: {e}"


def _cmd_add(message):
    """Add a new reminder."""
    reminders = _load()
    new_id = _next_id(reminders)
    entry = {
        "id": new_id,
        "message": message,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "done": False,
    }
    reminders.append(entry)
    _save(reminders)
    return f"Reminder #{new_id} added: {message}"


def _cmd_list():
    """List all reminders grouped by status."""
    reminders = _load()
    if not reminders:
        return "No reminders. Use 'remind add <message>' to create one."

    active = [r for r in reminders if not r.get("done")]
    completed = [r for r in reminders if r.get("done")]

    lines = []
    if active:
        lines.append(f"Active ({len(active)}):")
        for r in active:
            lines.append(f"  [{r['id']}] {r['message']}  (added {r.get('created', '?')})")
    if completed:
        lines.append(f"Completed ({len(completed)}):")
        for r in completed:
            lines.append(f"  [{r['id']}] {r['message']}  (done)")

    if not active and completed:
        lines.insert(0, "All reminders completed. Use 'remind clear' to clean up.")

    return "\n".join(lines)


def _cmd_done(id_str):
    """Mark a reminder as complete by id."""
    try:
        target_id = int(id_str)
    except ValueError:
        return f"Invalid id '{id_str}' — must be a number."

    reminders = _load()
    for r in reminders:
        if r.get("id") == target_id:
            if r.get("done"):
                return f"Reminder #{target_id} is already marked done."
            r["done"] = True
            _save(reminders)
            return f"Reminder #{target_id} marked done: {r['message']}"

    return f"No reminder found with id {target_id}."


def _cmd_clear():
    """Remove all completed reminders from disk."""
    reminders = _load()
    before = len(reminders)
    reminders = [r for r in reminders if not r.get("done")]
    after = len(reminders)
    removed = before - after

    if removed == 0:
        return "Nothing to clear — no completed reminders."

    _save(reminders)
    return f"Cleared {removed} completed reminder(s). {after} active remaining."
