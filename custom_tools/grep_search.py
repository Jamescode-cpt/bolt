"""BOLT custom tool — search inside files for patterns.

Pure stdlib using re + os.walk(). Restricted to /home/mobilenode/.
Skips binary files, capped at 50 matches.
"""

import os
import re

TOOL_NAME = "grep_search"
TOOL_DESC = (
    "Search inside files for a pattern (regex). "
    'Usage: <tool name="grep_search">TOOL_NAME\n/home/mobilenode/bolt</tool> — '
    "line 1 = pattern, optional line 2 = directory (default: ~/)"
)

ALLOWED_ROOT = "/home/mobilenode"
MAX_MATCHES = 50
MAX_LINE_LEN = 200
# Skip files larger than this
MAX_FILE_SIZE = 1_000_000  # 1MB
# Skip these directory names
SKIP_DIRS = {".git", ".cache", "__pycache__", "node_modules", ".venv", "venv", ".local"}


def _is_binary(path):
    """Quick binary check — read first 1024 bytes for null bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
        return b"\x00" in chunk
    except Exception:
        return True


def run(args):
    """Search files for a regex pattern.

    Args: line 1 = regex pattern, optional line 2 = search directory.
    """
    raw = args.strip() if args else ""
    if not raw:
        return "No pattern provided. Usage: <tool name=\"grep_search\">pattern\\n/path/to/search</tool>"

    lines = raw.split("\n", 1)
    pattern_str = lines[0].strip()
    search_dir = lines[1].strip() if len(lines) > 1 else ALLOWED_ROOT

    search_dir = os.path.expanduser(search_dir)
    search_dir = os.path.realpath(search_dir)

    if not search_dir.startswith(ALLOWED_ROOT):
        return f"Access denied: search restricted to {ALLOWED_ROOT}/"

    if not os.path.isdir(search_dir):
        return f"Not a directory: {search_dir}"

    try:
        regex = re.compile(pattern_str, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex: {e}"

    results = []
    files_searched = 0

    try:
        for root, dirs, files in os.walk(search_dir):
            # Skip hidden/unwanted dirs
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]

            for fname in files:
                fpath = os.path.join(root, fname)

                # Skip large files
                try:
                    if os.path.getsize(fpath) > MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue

                # Skip binary
                if _is_binary(fpath):
                    continue

                files_searched += 1

                try:
                    with open(fpath, "r", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if regex.search(line):
                                rel = os.path.relpath(fpath, ALLOWED_ROOT)
                                display_line = line.rstrip()
                                if len(display_line) > MAX_LINE_LEN:
                                    display_line = display_line[:MAX_LINE_LEN] + "..."
                                results.append(f"  {rel}:{lineno}: {display_line}")
                                if len(results) >= MAX_MATCHES:
                                    break
                except Exception:
                    continue

                if len(results) >= MAX_MATCHES:
                    break
            if len(results) >= MAX_MATCHES:
                break

        if not results:
            return f"No matches for '{pattern_str}' in {search_dir} ({files_searched} files searched)"

        header = f"Found {len(results)} match{'es' if len(results) != 1 else ''} for '{pattern_str}' ({files_searched} files searched):"
        if len(results) >= MAX_MATCHES:
            header += f" (capped at {MAX_MATCHES})"
        return header + "\n" + "\n".join(results)

    except Exception as e:
        return f"grep_search error: {e}"
