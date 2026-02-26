"""BOLT custom tool — take screenshots.

Tries available screenshot tools in order: grim (Wayland) > gnome-screenshot > scrot > import (ImageMagick).
Returns clear install instructions if none are found.
"""

import subprocess
import os
import shutil
import time

TOOL_NAME = "screenshot"
TOOL_DESC = (
    "Take a screenshot. "
    'Usage: <tool name="screenshot">take</tool> — '
    "saves to ~/screenshots/ and returns the file path"
)

SCREENSHOT_DIR = "/home/mobilenode/screenshots"

# Screenshot tools in preference order: (binary, args_template, description)
# {output} will be replaced with the output file path
TOOLS = [
    ("grim", ["{output}"], "grim (Wayland)"),
    ("gnome-screenshot", ["-f", "{output}"], "gnome-screenshot"),
    ("scrot", ["{output}"], "scrot (X11)"),
    ("import", ["-window", "root", "{output}"], "ImageMagick import"),
    ("spectacle", ["-b", "-n", "-o", "{output}"], "KDE Spectacle"),
]


def _find_tool():
    """Find the first available screenshot tool."""
    for binary, args_tmpl, desc in TOOLS:
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
            return (
                "No screenshot tool found. Install one of these:\n\n"
                "  Wayland (recommended for ROG Ally X):\n"
                "    sudo pacman -S grim      # Arch/SteamOS\n"
                "    sudo apt install grim     # Debian/Ubuntu\n\n"
                "  X11:\n"
                "    sudo pacman -S scrot\n"
                "    sudo apt install scrot\n\n"
                "  Desktop environment:\n"
                "    gnome-screenshot (GNOME)\n"
                "    spectacle (KDE)\n\n"
                "  Universal:\n"
                "    sudo pacman -S imagemagick  # provides 'import' command"
            )

        # Create output directory
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

        # Generate filename
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(SCREENSHOT_DIR, f"screenshot_{timestamp}.png")

        # Build command
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
