"""BOLT custom tool — system resource monitor with threshold alerts.

Pure stdlib — reads /proc, /sys, and df directly. No external deps.
Persists alert thresholds to ~/bolt/monitor_thresholds.json.
"""

import json
import os
import time

TOOL_NAME = "monitor"
TOOL_DESC = (
    "System monitor with threshold alerts. "
    'Usage: <tool name="monitor">check</tool> — one-shot resource check | '
    '<tool name="monitor">thresholds</tool> — view alert thresholds | '
    '<tool name="monitor">set cpu 90</tool> — set CPU alert threshold'
)

HOME = "/home/mobilenode"
THRESHOLDS_FILE = os.path.join(HOME, "bolt", "monitor_thresholds.json")

DEFAULT_THRESHOLDS = {
    "cpu": 90.0,
    "ram": 85.0,
    "disk": 90.0,
    "temp": 85.0,
}


def _read_file(path):
    """Read a file, return contents or None."""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return None


def _load_thresholds():
    """Load thresholds from file, merging with defaults."""
    thresholds = dict(DEFAULT_THRESHOLDS)
    try:
        if os.path.exists(THRESHOLDS_FILE):
            with open(THRESHOLDS_FILE, "r") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k in DEFAULT_THRESHOLDS:
                    if k in saved:
                        try:
                            thresholds[k] = float(saved[k])
                        except (ValueError, TypeError):
                            pass
    except Exception:
        pass
    return thresholds


def _save_thresholds(thresholds):
    """Persist thresholds to file."""
    try:
        # Validate path stays under home
        real_path = os.path.realpath(THRESHOLDS_FILE)
        if not real_path.startswith(HOME):
            return "Error: threshold file path escapes home directory."
        os.makedirs(os.path.dirname(THRESHOLDS_FILE), exist_ok=True)
        with open(THRESHOLDS_FILE, "w") as f:
            json.dump(thresholds, f, indent=2)
        return None
    except Exception as e:
        return f"Failed to save thresholds: {e}"


def _check_cpu(thresholds):
    """Measure CPU usage over 0.5s from /proc/stat."""
    def read_stat():
        raw = _read_file("/proc/stat")
        if not raw:
            return None
        for line in raw.splitlines():
            if line.startswith("cpu "):
                vals = list(map(int, line.split()[1:]))
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                total = sum(vals)
                return total, idle
        return None

    s1 = read_stat()
    if not s1:
        return "CPU: unable to read /proc/stat", False
    time.sleep(0.5)
    s2 = read_stat()
    if not s2:
        return "CPU: unable to read /proc/stat", False

    d_total = s2[0] - s1[0]
    d_idle = s2[1] - s1[1]
    if d_total == 0:
        return "CPU: 0.0%", False
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
        load_str = f"  Load: {' '.join(parts)}"

    alert = usage >= thresholds["cpu"]
    status = "ALERT" if alert else "OK"
    line = f"CPU: {usage:.1f}% ({cores} cores){load_str}  [{status}]"
    if alert:
        line += f"  *** ABOVE {thresholds['cpu']:.0f}% THRESHOLD ***"
    return line, alert


def _check_ram(thresholds):
    """Check RAM usage from /proc/meminfo."""
    raw = _read_file("/proc/meminfo")
    if not raw:
        return "RAM: unable to read /proc/meminfo", False

    info = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            key = parts[0].rstrip(":")
            try:
                info[key] = int(parts[1])
            except ValueError:
                pass

    total_kb = info.get("MemTotal", 0)
    avail_kb = info.get("MemAvailable", 0)
    used_kb = total_kb - avail_kb

    def fmt(kb):
        if kb > 1048576:
            return f"{kb / 1048576:.1f} GB"
        return f"{kb / 1024:.0f} MB"

    pct = (used_kb / total_kb * 100) if total_kb else 0
    alert = pct >= thresholds["ram"]
    status = "ALERT" if alert else "OK"

    line = f"RAM: {fmt(used_kb)} / {fmt(total_kb)} ({pct:.1f}%)  [{status}]"
    if alert:
        line += f"  *** ABOVE {thresholds['ram']:.0f}% THRESHOLD ***"

    # Swap info
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = swap_total - swap_free
    if swap_total:
        swap_pct = swap_used / swap_total * 100
        line += f"\nSwap: {fmt(swap_used)} / {fmt(swap_total)} ({swap_pct:.0f}%)"

    return line, alert


def _check_disk(thresholds):
    """Check disk usage via os.statvfs."""
    try:
        st = os.statvfs(HOME)
        total = st.f_blocks * st.f_frsize
        free = st.f_bfree * st.f_frsize
        used = total - free

        def fmt(b):
            if b > 1073741824:
                return f"{b / 1073741824:.1f} GB"
            return f"{b / 1048576:.0f} MB"

        pct = (used / total * 100) if total else 0
        alert = pct >= thresholds["disk"]
        status = "ALERT" if alert else "OK"

        line = f"Disk ({HOME}): {fmt(used)} / {fmt(total)} ({pct:.1f}%)  [{status}]"
        if alert:
            line += f"  *** ABOVE {thresholds['disk']:.0f}% THRESHOLD ***"
        return line, alert
    except Exception as e:
        return f"Disk: error — {e}", False


def _check_temps(thresholds):
    """Check temperatures from /sys/class/thermal/."""
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return "Temps: no thermal sysfs found", False

    results = []
    any_alert = False

    for entry in sorted(os.listdir(base)):
        if not entry.startswith("thermal_zone"):
            continue
        path = os.path.join(base, entry)
        temp_raw = _read_file(os.path.join(path, "temp"))
        type_name = _read_file(os.path.join(path, "type")) or entry
        if temp_raw:
            try:
                temp_c = int(temp_raw) / 1000.0
                alert = temp_c >= thresholds["temp"]
                if alert:
                    any_alert = True
                marker = " *** HOT ***" if alert else ""
                results.append(f"  {type_name}: {temp_c:.1f}C{marker}")
            except ValueError:
                pass

    if not results:
        return "Temps: no thermal zones reporting", False

    status = "ALERT" if any_alert else "OK"
    header = f"Temps [{status}]:"
    if any_alert:
        header += f"  (threshold: {thresholds['temp']:.0f}C)"
    return header + "\n" + "\n".join(results), any_alert


def _cmd_check():
    """Full one-shot resource check with threshold alerts."""
    thresholds = _load_thresholds()

    sections = []
    alerts = []

    cpu_line, cpu_alert = _check_cpu(thresholds)
    sections.append(cpu_line)
    if cpu_alert:
        alerts.append("CPU")

    ram_line, ram_alert = _check_ram(thresholds)
    sections.append(ram_line)
    if ram_alert:
        alerts.append("RAM")

    disk_line, disk_alert = _check_disk(thresholds)
    sections.append(disk_line)
    if disk_alert:
        alerts.append("Disk")

    temp_line, temp_alert = _check_temps(thresholds)
    sections.append(temp_line)
    if temp_alert:
        alerts.append("Temp")

    output = "\n\n".join(sections)

    if alerts:
        output = (
            f"=== ALERTS: {', '.join(alerts)} ===\n\n"
            + output
            + "\n\n=== Action may be needed ==="
        )
    else:
        output = "=== All systems nominal ===\n\n" + output

    return output


def _cmd_thresholds():
    """Show current alert thresholds."""
    thresholds = _load_thresholds()
    lines = ["Current alert thresholds:"]
    lines.append(f"  CPU usage:    {thresholds['cpu']:.0f}%")
    lines.append(f"  RAM usage:    {thresholds['ram']:.0f}%")
    lines.append(f"  Disk usage:   {thresholds['disk']:.0f}%")
    lines.append(f"  Temperature:  {thresholds['temp']:.0f}C")
    lines.append(f"\nStored in: {THRESHOLDS_FILE}")
    return "\n".join(lines)


def _cmd_set(rest):
    """Set a threshold value. Format: set <metric> <value>"""
    parts = rest.split()
    if len(parts) < 2:
        return (
            "Usage: set <metric> <value>\n"
            "Metrics: cpu, ram, disk, temp\n"
            "Example: set cpu 90"
        )

    metric = parts[0].lower()
    if metric not in DEFAULT_THRESHOLDS:
        return f"Unknown metric: {metric}\nValid metrics: {', '.join(DEFAULT_THRESHOLDS.keys())}"

    try:
        value = float(parts[1])
    except ValueError:
        return f"Invalid value: {parts[1]} — must be a number."

    if value < 0 or value > 100:
        if metric != "temp" or value > 150:
            return f"Value {value} out of reasonable range (0-100 for percentages, 0-150 for temp)."

    thresholds = _load_thresholds()
    old_value = thresholds[metric]
    thresholds[metric] = value

    err = _save_thresholds(thresholds)
    if err:
        return err

    unit = "C" if metric == "temp" else "%"
    return f"Threshold updated: {metric} {old_value:.0f}{unit} -> {value:.0f}{unit}"


def run(args):
    """System resource monitor with threshold alerts.

    Args: 'check' | 'thresholds' | 'set <metric> <value>'
    """
    raw = args.strip() if args else "check"

    try:
        parts = raw.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "check":
            return _cmd_check()
        elif cmd in ("thresholds", "threshold", "limits"):
            return _cmd_thresholds()
        elif cmd == "set":
            return _cmd_set(rest)
        else:
            return (
                "Monitor commands:\n"
                "  check              — one-shot resource check with alerts\n"
                "  thresholds         — view current alert thresholds\n"
                "  set <metric> <val> — set threshold (cpu, ram, disk, temp)\n"
                f"\nUnknown command: {cmd}"
            )
    except Exception as e:
        return f"monitor error: {e}"
