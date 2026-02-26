"""
BOLT Custom Tool: uptime
Shows system uptime, load averages, and boot time.
Reads from /proc/uptime and /proc/loadavg — no external deps.
"""

TOOL_NAME = "uptime"
TOOL_DESC = "Show system uptime, load averages, and boot time. No args needed."


def run(args):
    """Reads /proc/uptime and /proc/loadavg, returns a formatted summary."""
    try:
        # --- uptime ---
        try:
            with open("/proc/uptime", "r") as f:
                raw = f.read().strip().split()
            uptime_secs = float(raw[0])
        except (FileNotFoundError, PermissionError, ValueError) as e:
            return f"Error reading /proc/uptime: {e}"

        days = int(uptime_secs // 86400)
        hours = int((uptime_secs % 86400) // 3600)
        minutes = int((uptime_secs % 3600) // 60)
        seconds = int(uptime_secs % 60)

        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        uptime_str = " ".join(parts)

        # --- load averages ---
        try:
            with open("/proc/loadavg", "r") as f:
                load_raw = f.read().strip().split()
            load_str = f"{load_raw[0]} {load_raw[1]} {load_raw[2]}"
        except (FileNotFoundError, PermissionError, ValueError) as e:
            load_str = f"unavailable ({e})"

        # --- boot time ---
        import datetime
        try:
            boot_ts = datetime.datetime.now() - datetime.timedelta(seconds=uptime_secs)
            boot_str = boot_ts.strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            boot_str = f"unavailable ({e})"

        return f"Up {uptime_str} | Load: {load_str} | Boot: {boot_str}"

    except Exception as e:
        return f"uptime tool error: {e}"
