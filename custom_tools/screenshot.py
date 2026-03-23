"""BOLT custom tool — take screenshots.

Cross-platform: macOS (screencapture), Linux (grim, scrot, gnome-screenshot, etc.).
"""

import subprocess
import os
import shutil
import time
import sys

TOOL_NAME = "screenshot"
TOOL_DESC = (
    "Take a screenshot. "
    'Usage: <tool name="screenshot">take</tool> — '
    "saves to ~/screenshots/ and returns the file path"
)

SCREENSHOT_DIR = os.path.join(os.path.expanduser("~"), "screenshots")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import get_screenshot_tools, IS_MAC


def _find_tool():
    """Find the first available screenshot tool."""
    for binary, args_tmpl, desc in get_screenshot_tools():
        if shutil.which(binary):
            return binary, args_tmpl, desc
    return None, None, None


def run(args):
    """Take a screenshot.

    Args: 'take' (default). Returns the saved file path or install instructions.
    """
    try:
        binary, args_tmpl, desc = _find_tool()

        if binary is None:
            if IS_MAC:
                return "screencapture not found — this should be built-in on macOS."
            return (
                "No screenshot tool found. Install one of these:\n\n"
                "  Wayland:\n"
                "    sudo apt install grim          # Wayland\n\n"
                "  X11:\n"
                "    sudo apt install scrot\n\n"
                "  Desktop environment:\n"
                "    gnome-screenshot (GNOME)\n"
                "    spectacle (KDE)\n\n"
                "  Universal:\n"
                "    sudo apt install imagemagick   # provides 'import' command"
            )

        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(SCREENSHOT_DIR, f"screenshot_{timestamp}.png")

        cmd_args = [binary] + [a.replace("{output}", output_path) for a in args_tmpl]

        result = subprocess.run(
            cmd_args, capture_output=True, text=True, timeout=10,
        )

        if os.path.isfile(output_path):
            size = os.path.getsize(output_path)
            return f"Screenshot saved: {output_path} ({size / 1024:.0f} KB)\nTool used: {desc}"
        else:
            err = result.stderr.strip() if result.stderr else "unknown error"
            return f"Screenshot failed ({desc}): {err}"

    except subprocess.TimeoutExpired:
        return "Screenshot timed out after 10s"
    except Exception as e:
        return f"screenshot error: {e}"
