"""BOLT custom tool: disk usage overview, directory sizing, and large file finder."""

import os
import shutil
import subprocess

TOOL_NAME = "disk"
TOOL_DESC = (
    "Disk usage utilities.\n"
    "  overview          - df -h style overview of all mounts\n"
    "  usage <path>      - size of a directory (du style)\n"
    "  largest <path>    - top 10 largest files in a directory"
)

ALLOWED_ROOT = "/home/mobilenode/"


def _safe_path(path):
    """Resolve and validate that a path lives under the allowed root."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not resolved.startswith(ALLOWED_ROOT):
        raise PermissionError(f"Access denied: path must be under {ALLOWED_ROOT}")
    return resolved


def _human_size(nbytes):
    """Convert bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024.0:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f} PB"


def _overview():
    """Show disk usage for all mounted filesystems (like df -h)."""
    try:
        result = subprocess.run(
            ["df", "-h", "--output=source,fstype,size,used,avail,pcent,target"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return f"Error running df: {result.stderr.strip()}"
        return result.stdout.strip()
    except FileNotFoundError:
        # Fallback: use shutil for just the root and home partitions
        lines = ["Filesystem overview (fallback mode):"]
        for mount in ["/", "/home"]:
            try:
                usage = shutil.disk_usage(mount)
                lines.append(
                    f"  {mount}: total={_human_size(usage.total)}  "
                    f"used={_human_size(usage.used)}  "
                    f"free={_human_size(usage.free)}  "
                    f"({usage.used * 100 // usage.total}%)"
                )
            except OSError:
                pass
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return "Error: df command timed out."


def _usage(path):
    """Show the total size of a directory tree using du."""
    try:
        safe = _safe_path(path)
    except PermissionError as e:
        return str(e)

    if not os.path.exists(safe):
        return f"Error: '{safe}' does not exist."

    try:
        result = subprocess.run(
            ["du", "-sh", safe],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            # du may emit warnings on permission errors; still show stdout
            output = result.stdout.strip()
            if output:
                return output + "\n(some paths may have been inaccessible)"
            return f"Error running du: {result.stderr.strip()}"
        return result.stdout.strip()
    except FileNotFoundError:
        # Fallback: walk manually
        total = 0
        for dirpath, _dirnames, filenames in os.walk(safe):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return f"{_human_size(total)}  {safe}"
    except subprocess.TimeoutExpired:
        return "Error: du command timed out (directory may be very large)."


def _largest(path):
    """Find the top 10 largest files under a directory."""
    try:
        safe = _safe_path(path)
    except PermissionError as e:
        return str(e)

    if not os.path.isdir(safe):
        return f"Error: '{safe}' is not a directory or does not exist."

    files = []
    try:
        for dirpath, _dirnames, filenames in os.walk(safe):
            for fname in filenames:
                fp = os.path.join(dirpath, fname)
                try:
                    size = os.path.getsize(fp)
                    files.append((size, fp))
                except OSError:
                    pass
    except OSError as e:
        return f"Error walking directory: {e}"

    if not files:
        return f"No files found under {safe}"

    files.sort(reverse=True)
    top = files[:10]

    lines = [f"Top {len(top)} largest files in {safe}:", ""]
    for i, (size, fp) in enumerate(top, 1):
        rel = os.path.relpath(fp, safe)
        lines.append(f"  {i:>2}. {_human_size(size):>10}  {rel}")

    total_all = sum(s for s, _ in files)
    lines.append(f"\nTotal files scanned: {len(files)}  |  Combined size: {_human_size(total_all)}")
    return "\n".join(lines)


def run(args):
    """Entry point called by BOLT tool loop."""
    args = (args or "").strip()
    if not args:
        return "Usage:\n" + TOOL_DESC

    parts = args.split(None, 1)
    command = parts[0].lower()

    if command == "overview":
        return _overview()

    if command == "usage":
        if len(parts) < 2:
            return "Error: provide a path.  Usage: usage <path>"
        return _usage(parts[1].strip())

    if command == "largest":
        if len(parts) < 2:
            return "Error: provide a path.  Usage: largest <path>"
        return _largest(parts[1].strip())

    return f"Unknown subcommand: '{command}'\n\n{TOOL_DESC}"
