"""BOLT custom tool — process manager.

Lists top processes by CPU/memory via /proc reads.
Can kill processes by PID (with safety checks).
Won't kill PID 1, root-owned procs, or BOLT itself.
"""

import os
import signal

TOOL_NAME = "processes"
TOOL_DESC = (
    "List top processes or kill by PID. "
    'Usage: <tool name="processes">top</tool> or '
    '<tool name="processes">top 20</tool> or '
    '<tool name="processes">kill 12345</tool>'
)

MY_PID = os.getpid()
MY_PPID = os.getppid()


def _get_clk_tck():
    """Get clock ticks per second."""
    try:
        return os.sysconf("SC_CLK_TCK")
    except Exception:
        return 100


def _read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return None


def _get_uptime():
    raw = _read_file("/proc/uptime")
    if raw:
        return float(raw.split()[0])
    return 0


def _get_total_mem():
    raw = _read_file("/proc/meminfo")
    if raw:
        for line in raw.splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1])  # kB
    return 1


def _list_procs():
    """Read all processes from /proc."""
    clk = _get_clk_tck()
    uptime = _get_uptime()
    total_mem = _get_total_mem()
    procs = []

    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        base = f"/proc/{pid}"

        # Read comm (process name)
        comm = _read_file(f"{base}/comm")
        if comm is None:
            continue
        comm = comm.strip()

        # Read stat for CPU info
        stat_raw = _read_file(f"{base}/stat")
        if not stat_raw:
            continue

        # Parse stat — fields are space-separated, but comm can contain spaces/parens
        # Find the closing paren to skip the comm field
        close_paren = stat_raw.rfind(")")
        if close_paren < 0:
            continue
        fields_after = stat_raw[close_paren + 2:].split()
        if len(fields_after) < 20:
            continue

        try:
            utime = int(fields_after[11])   # field 14 (0-indexed from after comm)
            stime = int(fields_after[12])   # field 15
            starttime = int(fields_after[19])  # field 22
        except (IndexError, ValueError):
            continue

        total_time = utime + stime
        proc_uptime = uptime - (starttime / clk)
        cpu_pct = (total_time / clk / proc_uptime * 100) if proc_uptime > 0 else 0

        # Read status for memory + UID
        status_raw = _read_file(f"{base}/status")
        rss_kb = 0
        uid = -1
        if status_raw:
            for line in status_raw.splitlines():
                if line.startswith("VmRSS:"):
                    try:
                        rss_kb = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass
                elif line.startswith("Uid:"):
                    try:
                        uid = int(line.split()[1])
                    except (IndexError, ValueError):
                        pass

        mem_pct = (rss_kb / total_mem * 100) if total_mem > 0 else 0

        procs.append({
            "pid": pid,
            "name": comm,
            "cpu": cpu_pct,
            "mem_pct": mem_pct,
            "rss_kb": rss_kb,
            "uid": uid,
        })

    return procs


def _format_top(count=15):
    """Format top processes by CPU usage."""
    procs = _list_procs()
    # Sort by CPU descending, then memory
    procs.sort(key=lambda p: (p["cpu"], p["mem_pct"]), reverse=True)
    top = procs[:count]

    if not top:
        return "No processes found"

    lines = [f"{'PID':>7}  {'CPU%':>5}  {'MEM%':>5}  {'RSS':>8}  NAME"]
    lines.append("-" * 45)
    for p in top:
        rss_str = f"{p['rss_kb'] / 1024:.0f}M" if p['rss_kb'] > 1024 else f"{p['rss_kb']}K"
        lines.append(
            f"{p['pid']:>7}  {p['cpu']:>5.1f}  {p['mem_pct']:>5.1f}  {rss_str:>8}  {p['name']}"
        )
    return "\n".join(lines)


def _kill_proc(pid_str):
    """Kill a process by PID with safety checks."""
    try:
        pid = int(pid_str.strip())
    except ValueError:
        return f"Invalid PID: {pid_str}"

    # Safety checks
    if pid <= 1:
        return "Refused: cannot kill PID 0 or 1 (kernel/init)"

    if pid == MY_PID or pid == MY_PPID:
        return "Refused: cannot kill BOLT's own process"

    # Check if it's a root process
    status = _read_file(f"/proc/{pid}/status")
    if status is None:
        return f"Process {pid} not found (already dead?)"

    uid = -1
    name = "unknown"
    for line in status.splitlines():
        if line.startswith("Uid:"):
            try:
                uid = int(line.split()[1])
            except (IndexError, ValueError):
                pass
        elif line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()

    if uid == 0:
        return f"Refused: PID {pid} ({name}) is owned by root. Use shell with sudo if you really need this."

    try:
        os.kill(pid, signal.SIGTERM)
        return f"Sent SIGTERM to PID {pid} ({name})"
    except PermissionError:
        return f"Permission denied: cannot kill PID {pid} ({name})"
    except ProcessLookupError:
        return f"Process {pid} not found (already dead?)"
    except Exception as e:
        return f"Kill error: {e}"


def run(args):
    """List processes or kill by PID.

    Args: 'top', 'top N', or 'kill PID'.
    """
    raw = args.strip().lower() if args else "top"

    try:
        if raw.startswith("kill"):
            parts = raw.split(None, 1)
            if len(parts) < 2:
                return "Usage: <tool name=\"processes\">kill 12345</tool>"
            return _kill_proc(parts[1])
        elif raw.startswith("top"):
            parts = raw.split()
            count = 15
            if len(parts) > 1:
                try:
                    count = min(int(parts[1]), 50)
                except ValueError:
                    pass
            return _format_top(count)
        else:
            # Default to top
            return _format_top()
    except Exception as e:
        return f"processes error: {e}"
