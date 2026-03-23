"""BOLT custom tool — system resource monitor with threshold alerts.

Cross-platform: Linux (/proc, /sys) and macOS (sysctl, vm_stat).
Persists alert thresholds to ~/bolt/monitor_thresholds.json.
"""

import json
import os
import sys

TOOL_NAME = "monitor"
TOOL_DESC = (
    "System monitor with threshold alerts. "
    'Usage: <tool name="monitor">check</tool> — one-shot resource check | '
    '<tool name="monitor">thresholds</tool> — view alert thresholds | '
    '<tool name="monitor">set cpu 90</tool> — set CPU alert threshold'
)

HOME = os.path.expanduser("~")
THRESHOLDS_FILE = os.path.join(HOME, "bolt", "monitor_thresholds.json")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import get_cpu_usage, get_ram_info, get_temps

DEFAULT_THRESHOLDS = {
    "cpu": 90.0,
    "ram": 85.0,
    "disk": 90.0,
    "temp": 85.0,
}


def _load_thresholds():
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
    try:
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
    usage, cores, load_str = get_cpu_usage()
    if usage is None:
        return f"CPU: unable to measure ({cores} cores)", False

    load_part = f"  Load: {load_str}" if load_str else ""
    alert = usage >= thresholds["cpu"]
    status = "ALERT" if alert else "OK"
    line = f"CPU: {usage:.1f}% ({cores} cores){load_part}  [{status}]"
    if alert:
        line += f"  *** ABOVE {thresholds['cpu']:.0f}% THRESHOLD ***"
    return line, alert


def _check_ram(thresholds):
    info = get_ram_info()
    if not info:
        return "RAM: unable to read memory info", False

    total_kb = info["total_kb"]
    used_kb = info["used_kb"]

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

    if info["swap_total_kb"]:
        swap_pct = info["swap_used_kb"] / info["swap_total_kb"] * 100
        line += f"\nSwap: {fmt(info['swap_used_kb'])} / {fmt(info['swap_total_kb'])} ({swap_pct:.0f}%)"

    return line, alert


def _check_disk(thresholds):
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
    temp_str = get_temps()

    # Try to parse temperatures for threshold checking
    any_alert = False
    if "°C" in temp_str or "°C" in temp_str:
        import re
        for match in re.finditer(r'(\d+\.?\d*)\s*°?C', temp_str):
            try:
                temp_c = float(match.group(1))
                if temp_c >= thresholds["temp"]:
                    any_alert = True
            except ValueError:
                pass

    status = "ALERT" if any_alert else "OK"
    if any_alert:
        return f"Temps [{status}] (threshold: {thresholds['temp']:.0f}°C):\n{temp_str}", True
    return temp_str, False


def _cmd_check():
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
    thresholds = _load_thresholds()
    lines = ["Current alert thresholds:"]
    lines.append(f"  CPU usage:    {thresholds['cpu']:.0f}%")
    lines.append(f"  RAM usage:    {thresholds['ram']:.0f}%")
    lines.append(f"  Disk usage:   {thresholds['disk']:.0f}%")
    lines.append(f"  Temperature:  {thresholds['temp']:.0f}°C")
    lines.append(f"\nStored in: {THRESHOLDS_FILE}")
    return "\n".join(lines)


def _cmd_set(rest):
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

    unit = "°C" if metric == "temp" else "%"
    return f"Threshold updated: {metric} {old_value:.0f}{unit} -> {value:.0f}{unit}"


def run(args):
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
