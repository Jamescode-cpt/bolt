"""BOLT custom tool — process manager.

Lists top processes by CPU/memory. Cross-platform: Linux (/proc) and macOS (ps).
Can kill processes by PID (with safety checks).
Won't kill PID 1, root-owned procs, or BOLT itself.
"""

import os
import signal
import sys

TOOL_NAME = "processes"
TOOL_DESC = (
    "List top processes or kill by PID. "
    'Usage: <tool name="processes">top</tool> or '
    '<tool name="processes">top 20</tool> or '
    '<tool name="processes">kill 12345</tool>'
)

MY_PID = os.getpid()
MY_PPID = os.getppid()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import get_process_list, IS_LINUX


def _format_top(count=15):
    """Format top processes by CPU usage."""
    procs = get_process_list()
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

    if pid <= 1:
        return "Refused: cannot kill PID 0 or 1 (kernel/init)"

    if pid == MY_PID or pid == MY_PPID:
        return "Refused: cannot kill BOLT's own process"

    # Check process ownership
    name = "unknown"
    uid = -1

    if IS_LINUX:
        try:
            with open(f"/proc/{pid}/status") as f:
                status = f.read()
            for line in status.splitlines():
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])
                elif line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
        except FileNotFoundError:
            return f"Process {pid} not found (already dead?)"
        except Exception:
            pass
    else:
        # macOS: check via ps
        import subprocess
        try:
            out = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "user,comm"],
                text=True, timeout=5,
            )
            lines = out.strip().splitlines()
            if len(lines) > 1:
                parts = lines[1].split(None, 1)
                if parts[0] == "root":
                    uid = 0
                name = os.path.basename(parts[1]) if len(parts) > 1 else "unknown"
            else:
                return f"Process {pid} not found (already dead?)"
        except subprocess.CalledProcessError:
            return f"Process {pid} not found (already dead?)"
        except Exception:
            pass

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
            return _format_top()
    except Exception as e:
        return f"processes error: {e}"
