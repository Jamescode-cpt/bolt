"""
BOLT Custom Tool: uptime
Shows system uptime, load averages, and boot time.
Cross-platform: Linux (/proc) and macOS (sysctl).
"""

import os
import sys

TOOL_NAME = "uptime"
TOOL_DESC = "Show system uptime, load averages, and boot time. No args needed."

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import get_uptime_secs


def run(args):
    """Get uptime, load averages, and boot time."""
    try:
        uptime_secs = get_uptime_secs()
        if uptime_secs is None:
            return "Error: unable to determine system uptime"

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

        # Load averages — cross-platform via os.getloadavg()
        try:
            load = os.getloadavg()
            load_str = f"{load[0]:.2f} {load[1]:.2f} {load[2]:.2f}"
        except (OSError, AttributeError):
            load_str = "unavailable"

        # Boot time
        import datetime
        try:
            boot_ts = datetime.datetime.now() - datetime.timedelta(seconds=uptime_secs)
            boot_str = boot_ts.strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            boot_str = f"unavailable ({e})"

        return f"Up {uptime_str} | Load: {load_str} | Boot: {boot_str}"

    except Exception as e:
        return f"uptime tool error: {e}"
