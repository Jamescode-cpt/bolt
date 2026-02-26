"""BOLT custom tool — recursive file search.

Pure stdlib using pathlib.rglob(). Restricted to /home/mobilenode/.
Capped at 100 results to avoid flooding context.
"""

import os
from pathlib import Path

TOOL_NAME = "find_files"
TOOL_DESC = (
    "Find files by glob pattern. "
    'Usage: <tool name="find_files">*.py</tool> or '
    '<tool name="find_files">*.py\n/home/mobilenode/bolt</tool> — '
    "line 1 = pattern, optional line 2 = directory (default: ~/)"
)

ALLOWED_ROOT = "/home/mobilenode"
MAX_RESULTS = 100


def run(args):
    """Find files matching a glob pattern.

    Args: line 1 = glob pattern, optional line 2 = search directory.
    Restricted to /home/mobilenode/.
    """
    raw = args.strip() if args else ""
    if not raw:
        return "No pattern provided. Usage: <tool name=\"find_files\">*.py</tool>"

    lines = raw.split("\n", 1)
    pattern = lines[0].strip()
    search_dir = lines[1].strip() if len(lines) > 1 else ALLOWED_ROOT

    # Expand ~ and resolve
    search_dir = os.path.expanduser(search_dir)
    search_dir = os.path.realpath(search_dir)

    # Safety: restrict to home
    if not search_dir.startswith(ALLOWED_ROOT):
        return f"Access denied: search restricted to {ALLOWED_ROOT}/"

    if not os.path.isdir(search_dir):
        return f"Not a directory: {search_dir}"

    try:
        base = Path(search_dir)
        matches = []
        for p in base.rglob(pattern):
            # Skip hidden dirs deep inside (.git, .cache, etc.)
            parts = p.relative_to(base).parts
            if any(part.startswith(".") for part in parts[:-1]):
                continue
            rel = str(p.relative_to(ALLOWED_ROOT)) if str(p).startswith(ALLOWED_ROOT) else str(p)
            marker = "/" if p.is_dir() else ""
            matches.append(f"  {rel}{marker}")
            if len(matches) >= MAX_RESULTS:
                break

        if not matches:
            return f"No files matching '{pattern}' in {search_dir}"

        header = f"Found {len(matches)} match{'es' if len(matches) != 1 else ''} for '{pattern}' in {search_dir}:"
        if len(matches) >= MAX_RESULTS:
            header += f" (capped at {MAX_RESULTS})"
        return header + "\n" + "\n".join(matches)

    except Exception as e:
        return f"find_files error: {e}"
