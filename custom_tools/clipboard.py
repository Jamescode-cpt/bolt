"""BOLT custom tool — read/write system clipboard.

Tries: wl-paste/wl-copy (Wayland) > xclip > xsel (X11).
Returns install instructions if none are found.
"""

import subprocess
import shutil

TOOL_NAME = "clipboard"
TOOL_DESC = (
    "Read or write the system clipboard. "
    'Usage: <tool name="clipboard">read</tool> or '
    '<tool name="clipboard">write\ntext to copy</tool>'
)

# Clipboard backends: (read_cmd, write_cmd, description)
BACKENDS = [
    (["wl-paste"], ["wl-copy"], "wl-clipboard (Wayland)"),
    (["xclip", "-selection", "clipboard", "-o"], ["xclip", "-selection", "clipboard", "-i"], "xclip"),
    (["xsel", "--clipboard", "--output"], ["xsel", "--clipboard", "--input"], "xsel"),
]

MAX_CLIPBOARD = 10000  # Max chars to read/write


def _find_backend():
    """Find the first available clipboard backend."""
    for read_cmd, write_cmd, desc in BACKENDS:
        if shutil.which(read_cmd[0]):
            return read_cmd, write_cmd, desc
    return None, None, None


def _read_clipboard(read_cmd, desc):
    """Read from clipboard."""
    try:
        result = subprocess.run(
            read_cmd, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            err = result.stderr.strip() if result.stderr else "empty/error"
            return f"Clipboard read failed ({desc}): {err}"

        content = result.stdout
        if not content:
            return "Clipboard is empty"

        if len(content) > MAX_CLIPBOARD:
            content = content[:MAX_CLIPBOARD] + f"\n... (truncated, {len(result.stdout)} chars total)"

        return f"Clipboard contents ({desc}):\n{content}"

    except subprocess.TimeoutExpired:
        return "Clipboard read timed out"
    except Exception as e:
        return f"Clipboard read error: {e}"


def _write_clipboard(text, write_cmd, desc):
    """Write to clipboard."""
    if not text:
        return "Nothing to copy — provide text after 'write\\n'"

    if len(text) > MAX_CLIPBOARD:
        return f"Text too large ({len(text)} chars, max {MAX_CLIPBOARD})"

    try:
        result = subprocess.run(
            write_cmd, input=text, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            err = result.stderr.strip() if result.stderr else "unknown error"
            return f"Clipboard write failed ({desc}): {err}"

        return f"Copied {len(text)} chars to clipboard ({desc})"

    except subprocess.TimeoutExpired:
        return "Clipboard write timed out"
    except Exception as e:
        return f"Clipboard write error: {e}"


def run(args):
    """Read or write the system clipboard.

    Args: 'read' to read, or 'write\\ntext to copy' to write.
    """
    raw = args.strip() if args else "read"

    read_cmd, write_cmd, desc = _find_backend()
    if read_cmd is None:
        return (
            "No clipboard tool found. Install one of these:\n\n"
            "  Wayland (recommended for ROG Ally X):\n"
            "    sudo pacman -S wl-clipboard    # Arch/SteamOS\n"
            "    sudo apt install wl-clipboard   # Debian/Ubuntu\n\n"
            "  X11:\n"
            "    sudo pacman -S xclip\n"
            "    sudo apt install xclip\n\n"
            "  Alternative:\n"
            "    sudo pacman -S xsel\n"
            "    sudo apt install xsel"
        )

    try:
        lines = raw.split("\n", 1)
        action = lines[0].strip().lower()

        if action == "read":
            return _read_clipboard(read_cmd, desc)
        elif action == "write" or action == "copy":
            text = lines[1] if len(lines) > 1 else ""
            return _write_clipboard(text, write_cmd, desc)
        else:
            # Treat the whole thing as text to copy
            return _write_clipboard(raw, write_cmd, desc)

    except Exception as e:
        return f"clipboard error: {e}"
