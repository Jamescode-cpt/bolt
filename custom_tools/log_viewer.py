"""
BOLT Custom Tool: Log Viewer
Read-only log inspection — system logs, BOLT timeline, arbitrary log files.
File paths restricted to /home/mobilenode/.
"""

import os
import sqlite3
import subprocess
import re

TOOL_NAME = "logs"
TOOL_DESC = (
    "View and search log files. Commands:\n"
    "  system                    - recent system journal entries (last 30 lines)\n"
    "  bolt                      - BOLT's own timeline from its database\n"
    "  file <path>               - tail a log file (last 50 lines)\n"
    "  search <pattern> <path>   - search/grep a log file for a pattern"
)

ALLOWED_PREFIX = "/home/mobilenode/"
BOLT_DB = os.path.expanduser("~/bolt/bolt.db")


def _validate_path(path, label="Path"):
    """Ensure path is under /home/mobilenode/."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not resolved.startswith(ALLOWED_PREFIX):
        raise ValueError(
            f"{label} '{resolved}' is outside the allowed area ({ALLOWED_PREFIX}). Blocked."
        )
    return resolved


def _cmd_system():
    """Show recent system journal entries."""
    # Try journalctl first (systemd), fall back to /var/log/syslog
    try:
        result = subprocess.run(
            ["journalctl", "--no-pager", "-n", "30", "--output=short-iso"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip()
            return f"System journal (last 30 entries):\n{'=' * 60}\n{lines}"
        # journalctl might fail without privileges, fall through
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: try reading syslog (read-only, may need permission)
    syslog_paths = ["/var/log/syslog", "/var/log/messages"]
    for logpath in syslog_paths:
        if os.path.isfile(logpath):
            try:
                with open(logpath, "r") as f:
                    # Read last 30 lines efficiently
                    all_lines = f.readlines()
                    tail = all_lines[-30:]
                return (
                    f"System log ({logpath}, last 30 lines):\n"
                    f"{'=' * 60}\n"
                    f"{''.join(tail)}"
                )
            except PermissionError:
                continue
            except IOError as e:
                continue

    return (
        "Could not read system logs.\n"
        "journalctl returned no data and /var/log/syslog is not accessible.\n"
        "This may require elevated permissions."
    )


def _cmd_bolt():
    """Show BOLT's own timeline from the SQLite database."""
    if not os.path.isfile(BOLT_DB):
        return f"BOLT database not found at {BOLT_DB}"

    try:
        conn = sqlite3.connect(BOLT_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check which tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        lines = [f"BOLT Timeline (from {BOLT_DB})", "=" * 60]

        # Try timeline table first
        if "timeline" in tables:
            cursor.execute(
                "SELECT * FROM timeline ORDER BY rowid DESC LIMIT 30"
            )
            rows = cursor.fetchall()
            if rows:
                lines.append(f"\n--- timeline (last 30 entries) ---")
                columns = [desc[0] for desc in cursor.description]
                for row in rows:
                    entry_parts = []
                    for col in columns:
                        val = row[col]
                        if val is not None:
                            entry_parts.append(f"{col}={val}")
                    lines.append("  " + " | ".join(entry_parts))
            else:
                lines.append("timeline table exists but is empty.")

        # Also check messages table for recent activity
        if "messages" in tables:
            cursor.execute(
                "SELECT * FROM messages ORDER BY rowid DESC LIMIT 15"
            )
            rows = cursor.fetchall()
            if rows:
                lines.append(f"\n--- messages (last 15) ---")
                columns = [desc[0] for desc in cursor.description]
                for row in rows:
                    entry_parts = []
                    for col in columns:
                        val = row[col]
                        if val is not None:
                            # Truncate long message content
                            sval = str(val)
                            if len(sval) > 120:
                                sval = sval[:120] + "..."
                            entry_parts.append(f"{col}={sval}")
                    lines.append("  " + " | ".join(entry_parts))

        # Show summaries if available
        if "summaries" in tables:
            cursor.execute(
                "SELECT * FROM summaries ORDER BY rowid DESC LIMIT 5"
            )
            rows = cursor.fetchall()
            if rows:
                lines.append(f"\n--- summaries (last 5) ---")
                columns = [desc[0] for desc in cursor.description]
                for row in rows:
                    entry_parts = []
                    for col in columns:
                        val = row[col]
                        if val is not None:
                            sval = str(val)
                            if len(sval) > 200:
                                sval = sval[:200] + "..."
                            entry_parts.append(f"{col}={sval}")
                    lines.append("  " + " | ".join(entry_parts))

        if not tables:
            lines.append("Database exists but has no tables.")
        elif len(lines) == 2:
            lines.append(f"Tables found: {', '.join(tables)}")
            lines.append("No timeline, messages, or summaries data found.")

        conn.close()
        return "\n".join(lines)

    except sqlite3.Error as e:
        return f"Database error: {e}"


def _cmd_file(path_arg):
    """Tail a log file (last 50 lines)."""
    if not path_arg.strip():
        return "Error: provide a file path. Example: file ~/bolt/some.log"

    filepath = _validate_path(path_arg, "Log file")

    if not os.path.isfile(filepath):
        return f"Error: file not found: {filepath}"

    try:
        with open(filepath, "r", errors="replace") as f:
            all_lines = f.readlines()

        total = len(all_lines)
        tail = all_lines[-50:]
        start_line = max(total - 50, 0) + 1

        numbered = []
        for i, line in enumerate(tail):
            numbered.append(f"  {start_line + i:>6}  {line.rstrip()}")

        header = f"{filepath} ({total} total lines, showing last {len(tail)}):"
        return header + "\n" + "-" * 60 + "\n" + "\n".join(numbered)

    except PermissionError:
        return f"Error: permission denied reading {filepath}"
    except IOError as e:
        return f"Error reading file: {e}"


def _cmd_search(rest):
    """Search/grep a log file for a pattern."""
    parts = rest.strip().split(None, 1)
    if len(parts) < 2:
        return "Error: usage: search <pattern> <path>"

    pattern = parts[0]
    filepath = _validate_path(parts[1], "Log file")

    if not os.path.isfile(filepath):
        return f"Error: file not found: {filepath}"

    # Validate regex pattern
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Error: invalid regex pattern '{pattern}': {e}"

    try:
        matches = []
        with open(filepath, "r", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                if compiled.search(line):
                    matches.append(f"  {line_num:>6}  {line.rstrip()}")
                    # Cap results to prevent huge output
                    if len(matches) >= 200:
                        matches.append(f"  ... (truncated at 200 matches)")
                        break

        if not matches:
            return f"No matches for '{pattern}' in {filepath}"

        header = f"Search '{pattern}' in {filepath} ({len(matches)} match{'es' if len(matches) != 1 else ''}):"
        return header + "\n" + "-" * 60 + "\n" + "\n".join(matches)

    except PermissionError:
        return f"Error: permission denied reading {filepath}"
    except IOError as e:
        return f"Error reading file: {e}"


def run(args):
    """Entry point called by BOLT tool system."""
    try:
        args = (args or "").strip()
        parts = args.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "system":
            return _cmd_system()
        elif cmd == "bolt":
            return _cmd_bolt()
        elif cmd == "file":
            return _cmd_file(rest)
        elif cmd == "search":
            return _cmd_search(rest)
        else:
            return (
                f"Unknown command: '{cmd}'\n"
                "Available: system, bolt, file <path>, search <pattern> <path>"
            )
    except ValueError as e:
        return f"Security error: {e}"
    except Exception as e:
        return f"Log viewer error: {e}"
