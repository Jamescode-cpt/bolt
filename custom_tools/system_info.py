"""BOLT custom tool — system info (battery, CPU, RAM, disk, temps).

Pure stdlib — reads /proc and /sys directly. No external deps.
CPU measurement takes ~0.5s (two /proc/stat reads with a gap).
"""

import os
import time

TOOL_NAME = "system_info"
TOOL_DESC = (
    "Get system info: battery, CPU, RAM, disk, temps. "
    'Usage: <tool name="system_info">all</tool> or '
    '<tool name="system_info">battery</tool> — options: all, battery, cpu, ram, disk, temps'
)

HOME = "/home/mobilenode"


def _read_file(path):
    """Read a file, return contents or None."""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return None


def _battery():
    """Read battery info from /sys/class/power_supply/."""
    bat_dirs = []
    base = "/sys/class/power_supply"
    if not os.path.isdir(base):
        return "Battery: no power_supply sysfs found"
    for entry in os.listdir(base):
        typ = _read_file(os.path.join(base, entry, "type"))
        if typ and typ.lower() == "battery":
            bat_dirs.append(os.path.join(base, entry))
    if not bat_dirs:
        return "Battery: no battery detected (desktop or unsupported)"

    results = []
    for bat in bat_dirs:
        name = os.path.basename(bat)
        capacity = _read_file(os.path.join(bat, "capacity"))
        status = _read_file(os.path.join(bat, "status"))
        parts = [f"Battery ({name}):"]
        if capacity:
            parts.append(f"{capacity}%")
        if status:
            parts.append(f"[{status}]")
        results.append(" ".join(parts))
    return "\n".join(results)


def _cpu():
    """Measure CPU usage over 0.5s from /proc/stat."""
    def read_stat():
        raw = _read_file("/proc/stat")
        if not raw:
            return None
        for line in raw.splitlines():
            if line.startswith("cpu "):
                vals = list(map(int, line.split()[1:]))
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
                total = sum(vals)
                return total, idle
        return None

    s1 = read_stat()
    if not s1:
        return "CPU: unable to read /proc/stat"
    time.sleep(0.5)
    s2 = read_stat()
    if not s2:
        return "CPU: unable to read /proc/stat (second sample)"

    d_total = s2[0] - s1[0]
    d_idle = s2[1] - s1[1]
    if d_total == 0:
        return "CPU: 0.0% (no ticks elapsed)"
    usage = (1.0 - d_idle / d_total) * 100.0

    # Core count
    cores = 0
    raw = _read_file("/proc/stat")
    if raw:
        for line in raw.splitlines():
            if line.startswith("cpu") and line[3:4].isdigit():
                cores += 1

    # Load average
    loadavg = _read_file("/proc/loadavg")
    load_str = ""
    if loadavg:
        parts = loadavg.split()[:3]
        load_str = f"  Load avg: {' '.join(parts)}"

    return f"CPU: {usage:.1f}% usage ({cores} cores){load_str}"


def _ram():
    """Read RAM info from /proc/meminfo."""
    raw = _read_file("/proc/meminfo")
    if not raw:
        return "RAM: unable to read /proc/meminfo"

    info = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            try:
                info[key] = int(parts[1])  # kB
            except ValueError:
                pass

    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    used = total - avail

    def fmt(kb):
        if kb > 1048576:
            return f"{kb / 1048576:.1f} GB"
        return f"{kb / 1024:.0f} MB"

    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = swap_total - swap_free

    lines = [f"RAM: {fmt(used)} / {fmt(total)} ({100 * used / total:.0f}% used)"]
    if swap_total:
        lines.append(f"Swap: {fmt(swap_used)} / {fmt(swap_total)}")
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
    """Read thermal zones from /sys/class/thermal/."""
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return "Temps: no thermal sysfs found"

    results = []
    for entry in sorted(os.listdir(base)):
        if not entry.startswith("thermal_zone"):
            continue
        path = os.path.join(base, entry)
        temp_raw = _read_file(os.path.join(path, "temp"))
        type_name = _read_file(os.path.join(path, "type")) or entry
        if temp_raw:
            try:
                temp_c = int(temp_raw) / 1000.0
                results.append(f"  {type_name}: {temp_c:.1f}°C")
            except ValueError:
                pass
    if not results:
        return "Temps: no thermal zones reporting"
    return "Temps:\n" + "\n".join(results)


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
