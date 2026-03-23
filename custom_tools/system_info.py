"""BOLT custom tool — system info (battery, CPU, RAM, disk, temps).

Cross-platform: works on Linux (/proc, /sys) and macOS (sysctl, vm_stat, pmset).
CPU measurement takes ~0.5s (two samples with a gap).
"""

import os

TOOL_NAME = "system_info"
TOOL_DESC = (
    "Get system info: battery, CPU, RAM, disk, temps. "
    'Usage: <tool name="system_info">all</tool> or '
    '<tool name="system_info">battery</tool> — options: all, battery, cpu, ram, disk, temps'
)

HOME = os.path.expanduser("~")

# Import cross-platform helpers
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import (
    get_cpu_usage, get_ram_info, get_battery_info, get_temps,
)


def _battery():
    return get_battery_info()


def _cpu():
    usage, cores, load_str = get_cpu_usage()
    if usage is None:
        return f"CPU: unable to measure ({cores} cores)"
    load_part = f"  Load avg: {load_str}" if load_str else ""
    return f"CPU: {usage:.1f}% usage ({cores} cores){load_part}"


def _ram():
    info = get_ram_info()
    if not info:
        return "RAM: unable to read memory info"

    total = info["total_kb"]
    used = info["used_kb"]

    def fmt(kb):
        if kb > 1048576:
            return f"{kb / 1048576:.1f} GB"
        return f"{kb / 1024:.0f} MB"

    lines = [f"RAM: {fmt(used)} / {fmt(total)} ({100 * used / total:.0f}% used)"]
    if info["swap_total_kb"]:
        lines.append(f"Swap: {fmt(info['swap_used_kb'])} / {fmt(info['swap_total_kb'])}")
    return "\n".join(lines)


def _disk():
    """Disk usage for home partition via os.statvfs."""
    try:
        st = os.statvfs(HOME)
        total = st.f_blocks * st.f_frsize
        free = st.f_bfree * st.f_frsize
        used = total - free

        def fmt(b):
            if b > 1073741824:
                return f"{b / 1073741824:.1f} GB"
            return f"{b / 1048576:.0f} MB"

        pct = 100 * used / total if total else 0
        return f"Disk ({HOME}): {fmt(used)} / {fmt(total)} ({pct:.0f}% used)"
    except Exception as e:
        return f"Disk: error — {e}"


def _temps():
    return get_temps()


SECTIONS = {
    "battery": _battery,
    "cpu": _cpu,
    "ram": _ram,
    "disk": _disk,
    "temps": _temps,
}


def run(args):
    """Get system info. Args: 'all', 'battery', 'cpu', 'ram', 'disk', 'temps'."""
    query = args.strip().lower() if args else "all"

    try:
        if query == "all":
            parts = []
            for name, func in SECTIONS.items():
                parts.append(func())
            return "\n\n".join(parts)
        elif query in SECTIONS:
            return SECTIONS[query]()
        else:
            return (
                f"Unknown section: {query}\n"
                f"Valid options: all, {', '.join(SECTIONS.keys())}"
            )
    except Exception as e:
        return f"system_info error: {e}"
