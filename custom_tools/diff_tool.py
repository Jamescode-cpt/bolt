"""BOLT custom tool — file diff comparison.

Pure stdlib difflib.unified_diff. Both paths must be under ~/.
500KB max per file. 5000 char output cap.
"""

import os
import difflib

TOOL_NAME = "diff"
TOOL_DESC = (
    "Compare two files and show differences. "
    'Usage: <tool name="diff">file1.py\nfile2.py</tool> — '
    "unified diff output. Both files must be under ~/."
)

HOME = os.path.expanduser("~")
MAX_FILE_SIZE = 500 * 1024  # 500KB
MAX_OUTPUT = 5000


def _validate_path(path):
    """Validate path is under home directory."""
    expanded = os.path.realpath(os.path.expanduser(path))
    if not expanded.startswith(HOME):
        return None, f"Blocked: {path} is outside ~/. Only files under {HOME}/ allowed."
    return expanded, None


def run(args):
    """Compare two files with unified diff.

    Args: 'file1\\nfile2' — one file path per line.
    """
    raw = args.strip() if args else ""
    if not raw:
        return 'Usage: <tool name="diff">path/to/file1\npath/to/file2</tool>'

    lines = raw.strip().split("\n", 1)
    if len(lines) < 2:
        return "Need two file paths, one per line."

    path1, err1 = _validate_path(lines[0].strip())
    if err1:
        return err1
    path2, err2 = _validate_path(lines[1].strip())
    if err2:
        return err2

    if not os.path.isfile(path1):
        return f"File not found: {lines[0].strip()}"
    if not os.path.isfile(path2):
        return f"File not found: {lines[1].strip()}"

    # Check sizes
    size1 = os.path.getsize(path1)
    size2 = os.path.getsize(path2)
    if size1 > MAX_FILE_SIZE:
        return f"File too large: {lines[0].strip()} ({size1} bytes, max {MAX_FILE_SIZE})"
    if size2 > MAX_FILE_SIZE:
        return f"File too large: {lines[1].strip()} ({size2} bytes, max {MAX_FILE_SIZE})"

    try:
        with open(path1, "r") as f:
            content1 = f.readlines()
        with open(path2, "r") as f:
            content2 = f.readlines()
    except UnicodeDecodeError:
        return "Cannot diff binary files."
    except Exception as e:
        return f"Error reading files: {e}"

    diff = list(difflib.unified_diff(
        content1, content2,
        fromfile=lines[0].strip(),
        tofile=lines[1].strip(),
        lineterm="",
    ))

    if not diff:
        return "Files are identical."

    output = "\n".join(diff)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + f"\n\n... (truncated, {len(output)} chars total)"

    return output
