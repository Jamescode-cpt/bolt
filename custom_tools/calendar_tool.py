TOOL_NAME = "calendar"
TOOL_DESC = """Simple event and schedule manager with date-based views.

Commands:
  add <YYYY-MM-DD> <HH:MM> <title>  — add an event
  today                              — show today's events
  week                               — show this week's events (Mon-Sun)
  month                              — show this month's events
  list                               — show all upcoming events
  remove <id>                        — remove an event
  search <query>                     — search events by title

Examples:
  calendar add 2026-03-01 14:00 Team standup
  calendar add 2026-02-25 09:30 Morning coffee
  calendar today
  calendar week
  calendar month
  calendar list
  calendar remove 3
  calendar search standup

Events are stored in ~/bolt/calendar.json."""


import json
import os
import datetime


_CAL_FILE = os.path.expanduser("~/bolt/calendar.json")
_SAFE_BASE = os.path.realpath(os.path.expanduser("~/"))


def _load_events():
    """Load events list from disk."""
    if not os.path.exists(_CAL_FILE):
        return []
    try:
        with open(_CAL_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, IOError):
        return []


def _save_events(events):
    """Persist events list to disk."""
    real = os.path.realpath(_CAL_FILE)
    if not real.startswith(_SAFE_BASE):
        return "Error: Refusing to write outside home directory."
    try:
        os.makedirs(os.path.dirname(_CAL_FILE), exist_ok=True)
        with open(_CAL_FILE, "w") as f:
            json.dump(events, f, indent=2)
        return None
    except IOError as e:
        return f"Error saving calendar: {e}"


def _next_id(events):
    """Get the next auto-increment ID."""
    if not events:
        return 1
    return max(e.get("id", 0) for e in events) + 1


def _parse_date(date_str):
    """Parse YYYY-MM-DD, return date or None."""
    try:
        return datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def _parse_time(time_str):
    """Parse HH:MM, return time or None."""
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        return datetime.time(h, m)
    except (ValueError, TypeError, IndexError):
        return None


def _event_datetime(event):
    """Get a datetime from an event for sorting. Returns datetime.datetime."""
    d = _parse_date(event.get("date", ""))
    t = _parse_time(event.get("time", ""))
    if d is None:
        d = datetime.date(9999, 12, 31)
    if t is None:
        t = datetime.time(23, 59)
    return datetime.datetime.combine(d, t)


def _sort_events(events):
    """Return events sorted by date+time."""
    return sorted(events, key=_event_datetime)


def _is_past(event):
    """Check if an event is in the past."""
    now = datetime.datetime.now()
    return _event_datetime(event) < now


def _format_event_list(events, title_label="Events"):
    """Format a list of events as an aligned table."""
    if not events:
        return f"No {title_label.lower()} found."
    events = _sort_events(events)
    now = datetime.datetime.now()
    header = ["ID", "DATE", "TIME", "TITLE", ""]
    rows = []
    for e in events:
        eid = str(e.get("id", "?"))
        date = e.get("date", "?")
        time = e.get("time", "?")
        etitle = e.get("title", "(untitled)")
        if len(etitle) > 50:
            etitle = etitle[:47] + "..."
        marker = "[PAST]" if _is_past(e) else ""
        rows.append([eid, date, time, etitle, marker])
    return f"{title_label}:\n" + _fmt_table(header, rows)


def _fmt_table(header, rows):
    """Simple aligned table."""
    if not rows:
        return "(none)"
    all_rows = [header] + rows
    widths = []
    for col in range(len(header)):
        w = max(len(str(r[col])) if col < len(r) else 0 for r in all_rows)
        widths.append(min(w, 55))
    lines = []
    for row in all_rows:
        parts = [str(row[i]).ljust(widths[i]) for i in range(len(header))]
        lines.append("  ".join(parts).rstrip())
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    args = args.strip() if args else ""

    if not args:
        return (
            "Calendar — simple event/schedule manager.\n"
            "Commands: add <YYYY-MM-DD> <HH:MM> <title> | today | week | month | list | remove <id> | search <query>\n"
            "Example: calendar add 2026-03-01 14:00 Team standup"
        )

    parts = args.split()
    cmd = parts[0].lower()

    try:
        # ── add ──
        if cmd == "add":
            if len(parts) < 4:
                return "Usage: calendar add <YYYY-MM-DD> <HH:MM> <title>\nExample: calendar add 2026-03-01 14:00 Team standup"
            date_str = parts[1]
            time_str = parts[2]
            title = " ".join(parts[3:])

            d = _parse_date(date_str)
            if d is None:
                return f"Error: Invalid date '{date_str}'. Use YYYY-MM-DD format (e.g. 2026-03-01)."
            t = _parse_time(time_str)
            if t is None:
                return f"Error: Invalid time '{time_str}'. Use HH:MM format (e.g. 14:00)."
            if not title.strip():
                return "Error: Event title cannot be empty."

            events = _load_events()
            new_event = {
                "id": _next_id(events),
                "date": date_str,
                "time": time_str,
                "title": title.strip(),
                "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            events.append(new_event)
            err = _save_events(events)
            if err:
                return err

            day_name = d.strftime("%A")
            return f"Event #{new_event['id']} added: {date_str} ({day_name}) at {time_str} — {title}"

        # ── today ──
        elif cmd == "today":
            today = datetime.date.today().isoformat()
            events = _load_events()
            today_events = [e for e in events if e.get("date") == today]
            day_name = datetime.date.today().strftime("%A, %B %d, %Y")
            return _format_event_list(today_events, f"Today ({day_name})")

        # ── week ──
        elif cmd == "week":
            today = datetime.date.today()
            # Monday of this week
            monday = today - datetime.timedelta(days=today.weekday())
            sunday = monday + datetime.timedelta(days=6)
            events = _load_events()
            week_events = []
            for e in events:
                d = _parse_date(e.get("date", ""))
                if d and monday <= d <= sunday:
                    week_events.append(e)
            label = f"This week ({monday.isoformat()} to {sunday.isoformat()})"
            return _format_event_list(week_events, label)

        # ── month ──
        elif cmd == "month":
            today = datetime.date.today()
            year = today.year
            month = today.month
            events = _load_events()
            month_events = []
            for e in events:
                d = _parse_date(e.get("date", ""))
                if d and d.year == year and d.month == month:
                    month_events.append(e)
            month_name = today.strftime("%B %Y")
            return _format_event_list(month_events, f"Events in {month_name}")

        # ── list ──
        elif cmd == "list":
            events = _load_events()
            if not events:
                return "No events. Use 'calendar add <YYYY-MM-DD> <HH:MM> <title>' to create one."
            # Show all events, upcoming first, then past
            now = datetime.datetime.now()
            upcoming = [e for e in events if not _is_past(e)]
            past = [e for e in events if _is_past(e)]
            result_parts = []
            if upcoming:
                result_parts.append(_format_event_list(upcoming, "Upcoming events"))
            if past:
                result_parts.append(_format_event_list(past, "Past events"))
            if not result_parts:
                return "No events found."
            return "\n\n".join(result_parts)

        # ── remove ──
        elif cmd == "remove":
            if len(parts) < 2:
                return "Usage: calendar remove <id>"
            try:
                target_id = int(parts[1])
            except ValueError:
                return "Error: Argument must be an event ID (number)."
            events = _load_events()
            original_len = len(events)
            # Find the event first to show what was removed
            removed = None
            for e in events:
                if e.get("id") == target_id:
                    removed = e
                    break
            if not removed:
                return f"Event #{target_id} not found. Use 'calendar list' to see all events."
            events = [e for e in events if e.get("id") != target_id]
            err = _save_events(events)
            if err:
                return err
            return f"Removed event #{target_id}: {removed.get('date', '?')} {removed.get('time', '?')} — {removed.get('title', '?')}"

        # ── search ──
        elif cmd == "search":
            if len(parts) < 2:
                return "Usage: calendar search <query>"
            query = " ".join(parts[1:]).lower()
            events = _load_events()
            matches = [
                e for e in events
                if query in e.get("title", "").lower()
                or query in e.get("date", "")
            ]
            if not matches:
                return f"No events matching '{query}'."
            return _format_event_list(matches, f"Search results for '{query}'")

        else:
            return (
                f"Unknown calendar command: '{cmd}'\n"
                "Available: add | today | week | month | list | remove | search"
            )

    except Exception as e:
        return f"Calendar tool error: {e}"
