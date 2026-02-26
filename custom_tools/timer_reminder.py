"""BOLT custom tool — countdown timers and datetime reminders.

Daemon thread started at import time — checks timers.json every 10s.
Fires notify-send on trigger. Atomic writes for persistence.
Max 100 active timers. Completely isolated from Ollama/SQLite/workers.
"""

import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta

TOOL_NAME = "timer"
TOOL_DESC = (
    "Set countdown timers or datetime reminders. "
    'Usage: <tool name="timer">set 5m coffee break</tool> or '
    '<tool name="timer">remind 2026-02-24 09:00 standup</tool> or '
    '<tool name="timer">list</tool> or '
    '<tool name="timer">cancel ID</tool> or '
    '<tool name="timer">fired</tool>'
)

TIMERS_FILE = os.path.expanduser("~/bolt/timers.json")
MAX_TIMERS = 100
CHECK_INTERVAL = 10  # seconds

# Duration patterns: 30s, 5m, 2h, 1d, or combos like 1h30m
DURATION_RE = re.compile(r"(\d+)\s*(s|sec|second|seconds|m|min|minute|minutes|h|hr|hour|hours|d|day|days)")

_lock = threading.Lock()


def _load_timers():
    """Load timers from JSON file."""
    if not os.path.exists(TIMERS_FILE):
        return []
    try:
        with open(TIMERS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_timers(timers):
    """Save timers atomically (write to .tmp then rename)."""
    tmp = TIMERS_FILE + ".tmp"
    try:
        os.makedirs(os.path.dirname(TIMERS_FILE), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(timers, f, indent=2)
        os.replace(tmp, TIMERS_FILE)
    except Exception:
        # Best effort cleanup
        try:
            os.remove(tmp)
        except OSError:
            pass


def _parse_duration(text):
    """Parse duration string into seconds. Returns (seconds, None) or (None, error)."""
    matches = DURATION_RE.findall(text.lower())
    if not matches:
        return None, f"Invalid duration: {text}. Use formats like 30s, 5m, 2h, 1d, 1h30m"

    total = 0
    for amount_str, unit in matches:
        amount = int(amount_str)
        if unit.startswith("s"):
            total += amount
        elif unit.startswith("m"):
            total += amount * 60
        elif unit.startswith("h"):
            total += amount * 3600
        elif unit.startswith("d"):
            total += amount * 86400

    if total <= 0:
        return None, "Duration must be positive."
    if total > 30 * 86400:
        return None, "Max duration is 30 days."

    return total, None


def _parse_datetime(text):
    """Parse datetime string. Returns (ISO string, None) or (None, error)."""
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m-%d %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text.strip(), fmt)
            # If year not in format, assume current year
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            if dt < datetime.now():
                return None, f"Datetime is in the past: {dt.isoformat()}"
            return dt.isoformat(), None
        except ValueError:
            continue
    return None, f"Invalid datetime: {text}. Use YYYY-MM-DD HH:MM format."


def _fire_notification(label):
    """Send a desktop notification for a fired timer."""
    try:
        subprocess.Popen(
            ["notify-send", "-u", "critical", "BOLT Timer", label],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass  # Best effort — notification system might not be available


def _daemon_loop():
    """Background daemon that checks and fires timers."""
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            with _lock:
                timers = _load_timers()
                changed = False
                now = datetime.now().isoformat()

                for timer in timers:
                    if timer.get("fired"):
                        continue
                    if timer.get("fire_at", "") <= now:
                        _fire_notification(timer.get("label", "Timer fired!"))
                        timer["fired"] = True
                        timer["fired_at"] = now
                        changed = True

                if changed:
                    _save_timers(timers)
        except Exception:
            pass  # Daemon must never crash


# Start daemon thread on import
_daemon_thread = threading.Thread(target=_daemon_loop, daemon=True, name="bolt-timer-daemon")
_daemon_thread.start()


def _set_timer(args_text):
    """Set a countdown timer. Format: '<duration> [label]'."""
    parts = args_text.strip().split(None, 1)
    if not parts:
        return "Usage: set 5m label"

    # Try to parse the duration from the first part, or first few parts
    duration_text = parts[0]
    label = parts[1] if len(parts) > 1 else "Timer"

    # Handle compound durations like "1h30m" or "1h 30m"
    # Try the full args_text for duration, extract label from what's left
    secs, err = _parse_duration(duration_text)
    if err:
        # Try parsing from the full text
        secs, err = _parse_duration(args_text)
        if err:
            return err
        # Extract label as non-duration parts
        label = DURATION_RE.sub("", args_text).strip() or "Timer"

    fire_at = (datetime.now() + timedelta(seconds=secs)).isoformat()

    with _lock:
        timers = _load_timers()
        active = [t for t in timers if not t.get("fired")]
        if len(active) >= MAX_TIMERS:
            return f"Too many active timers ({MAX_TIMERS}). Cancel some first."

        timer_id = uuid.uuid4().hex[:8]
        timer = {
            "id": timer_id,
            "type": "countdown",
            "label": label,
            "fire_at": fire_at,
            "created_at": datetime.now().isoformat(),
            "duration_secs": secs,
            "fired": False,
        }
        timers.append(timer)
        _save_timers(timers)

    # Human-readable duration
    if secs >= 3600:
        dur_str = f"{secs // 3600}h{(secs % 3600) // 60}m"
    elif secs >= 60:
        dur_str = f"{secs // 60}m{secs % 60}s"
    else:
        dur_str = f"{secs}s"

    return f"Timer set: {label} in {dur_str} (ID: {timer_id}, fires at {fire_at[:19]})"


def _set_reminder(args_text):
    """Set a datetime reminder. Format: 'YYYY-MM-DD HH:MM label'."""
    # Try to parse datetime from the beginning
    # Expect at least "YYYY-MM-DD HH:MM" = 16 chars
    if len(args_text) < 10:
        return "Usage: remind YYYY-MM-DD HH:MM label"

    # Try different splits for the datetime part
    for split_pos in [19, 16, 10]:
        if len(args_text) >= split_pos:
            dt_text = args_text[:split_pos].strip()
            label = args_text[split_pos:].strip() or "Reminder"
            fire_at, err = _parse_datetime(dt_text)
            if not err:
                break
    else:
        return "Invalid datetime. Use: remind YYYY-MM-DD HH:MM label"

    with _lock:
        timers = _load_timers()
        active = [t for t in timers if not t.get("fired")]
        if len(active) >= MAX_TIMERS:
            return f"Too many active timers ({MAX_TIMERS}). Cancel some first."

        timer_id = uuid.uuid4().hex[:8]
        timer = {
            "id": timer_id,
            "type": "reminder",
            "label": label,
            "fire_at": fire_at,
            "created_at": datetime.now().isoformat(),
            "fired": False,
        }
        timers.append(timer)
        _save_timers(timers)

    return f"Reminder set: {label} at {fire_at[:19]} (ID: {timer_id})"


def _list_timers():
    """List all timers."""
    with _lock:
        timers = _load_timers()

    if not timers:
        return "No timers set."

    active = [t for t in timers if not t.get("fired")]
    fired = [t for t in timers if t.get("fired")]

    lines = []
    if active:
        lines.append(f"Active timers ({len(active)}):")
        for t in sorted(active, key=lambda x: x.get("fire_at", "")):
            fire_dt = t.get("fire_at", "?")[:19]
            lines.append(f"  [{t['id']}] {t['label']} — fires at {fire_dt} ({t.get('type', 'timer')})")

    if fired:
        recent = sorted(fired, key=lambda x: x.get("fired_at", ""), reverse=True)[:10]
        lines.append(f"\nRecently fired ({len(fired)} total, showing last {len(recent)}):")
        for t in recent:
            fired_dt = t.get("fired_at", "?")[:19]
            lines.append(f"  [{t['id']}] {t['label']} — fired at {fired_dt}")

    return "\n".join(lines)


def _cancel_timer(timer_id):
    """Cancel a timer by ID."""
    if not timer_id:
        return "No timer ID provided."

    with _lock:
        timers = _load_timers()
        found = None
        for i, t in enumerate(timers):
            if t.get("id") == timer_id:
                found = i
                break

        if found is None:
            return f"Timer not found: {timer_id}"

        removed = timers.pop(found)
        _save_timers(timers)

    return f"Cancelled timer: {removed['label']} (ID: {timer_id})"


def _fired_timers():
    """Show recently fired timers."""
    with _lock:
        timers = _load_timers()

    fired = [t for t in timers if t.get("fired")]
    if not fired:
        return "No fired timers."

    recent = sorted(fired, key=lambda x: x.get("fired_at", ""), reverse=True)[:20]
    lines = [f"Fired timers ({len(fired)} total, showing last {len(recent)}):"]
    for t in recent:
        fired_dt = t.get("fired_at", "?")[:19]
        lines.append(f"  [{t['id']}] {t['label']} — fired at {fired_dt}")

    return "\n".join(lines)


def run(args):
    """Manage timers and reminders.

    Args:
      - 'set <duration> [label]' — countdown timer (5m, 2h, 1h30m, etc.)
      - 'remind <datetime> [label]' — reminder at specific time (YYYY-MM-DD HH:MM)
      - 'list' — list all timers
      - 'cancel <ID>' — cancel a timer
      - 'fired' — show recently fired timers
    """
    raw = args.strip() if args else ""
    if not raw:
        return (
            'Usage:\n'
            '  <tool name="timer">set 5m coffee break</tool>\n'
            '  <tool name="timer">remind 2026-02-24 09:00 standup</tool>\n'
            '  <tool name="timer">list</tool>\n'
            '  <tool name="timer">cancel abc12345</tool>\n'
            '  <tool name="timer">fired</tool>'
        )

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd == "set":
            return _set_timer(arg)
        elif cmd == "remind" or cmd == "reminder":
            return _set_reminder(arg)
        elif cmd == "list" or cmd == "ls":
            return _list_timers()
        elif cmd == "cancel" or cmd == "rm" or cmd == "delete":
            return _cancel_timer(arg)
        elif cmd == "fired" or cmd == "history":
            return _fired_timers()
        else:
            return f"Unknown subcommand: {cmd}. Available: set, remind, list, cancel, fired"
    except Exception as e:
        return f"timer error: {e}"
