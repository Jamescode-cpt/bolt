"""BOLT custom tool — text-to-speech.

Tries espeak > espeak-ng > spd-say > piper in order.
Non-blocking (subprocess.Popen). Speed/pitch options.
1000 char text cap.
"""

import subprocess
import shutil

TOOL_NAME = "speak"
TOOL_DESC = (
    "Text-to-speech (non-blocking). "
    'Usage: <tool name="speak">Hello world</tool> or '
    '<tool name="speak">speed=150\nHello world</tool> — '
    "options: speed=N (WPM), pitch=N (Hz)"
)

MAX_TEXT = 1000

# TTS backends in preference order: (binary, build_cmd_func, description)
BACKENDS = [
    "espeak",
    "espeak-ng",
    "spd-say",
    "piper",
]


def _find_backend():
    """Find the first available TTS backend."""
    for name in BACKENDS:
        if shutil.which(name):
            return name
    return None


def _build_cmd(backend, text, speed=None, pitch=None):
    """Build the command for the given backend."""
    if backend == "espeak":
        cmd = ["espeak"]
        if speed:
            cmd += ["-s", str(speed)]
        if pitch:
            cmd += ["-p", str(pitch)]
        cmd.append(text)
        return cmd

    elif backend == "espeak-ng":
        cmd = ["espeak-ng"]
        if speed:
            cmd += ["-s", str(speed)]
        if pitch:
            cmd += ["-p", str(pitch)]
        cmd.append(text)
        return cmd

    elif backend == "spd-say":
        cmd = ["spd-say"]
        if speed:
            # spd-say uses -r for rate (-100 to 100)
            # Map WPM roughly: 175 WPM is default (0), scale from there
            rate = max(-100, min(100, int((int(speed) - 175) / 2)))
            cmd += ["-r", str(rate)]
        if pitch:
            # spd-say uses -p for pitch (-100 to 100)
            pitch_val = max(-100, min(100, int(pitch)))
            cmd += ["-p", str(pitch_val)]
        cmd.append(text)
        return cmd

    elif backend == "piper":
        # Piper reads from stdin and pipes to aplay
        # This is handled differently
        return ["piper", "--output-raw"]

    return None


def run(args):
    """Speak text aloud (non-blocking).

    Args: text to speak, or 'speed=N\\npitch=N\\ntext to speak'.
    Options on separate lines before the text: speed=N (WPM), pitch=N (Hz).
    """
    raw = args.strip() if args else ""
    if not raw:
        return 'Usage: <tool name="speak">text to speak</tool>'

    # Parse options from leading lines
    lines = raw.split("\n")
    speed = None
    pitch = None
    text_lines = []

    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("speed="):
            try:
                speed = int(stripped.split("=", 1)[1])
            except ValueError:
                return "Invalid speed value. Use speed=N where N is words per minute."
        elif stripped.startswith("pitch="):
            try:
                pitch = int(stripped.split("=", 1)[1])
            except ValueError:
                return "Invalid pitch value. Use pitch=N."
        else:
            text_lines.append(line)

    text = "\n".join(text_lines).strip()

    if not text:
        return "No text provided."
    if len(text) > MAX_TEXT:
        return f"Text too long ({len(text)} chars, max {MAX_TEXT})."

    backend = _find_backend()
    if not backend:
        return (
            "No TTS engine found. Install one of these:\n\n"
            "  espeak (recommended, lightest):\n"
            "    sudo apt install espeak\n\n"
            "  espeak-ng (newer fork):\n"
            "    sudo apt install espeak-ng\n\n"
            "  spd-say (speech-dispatcher):\n"
            "    sudo apt install speech-dispatcher\n\n"
            "  piper (neural TTS, best quality, needs model download):\n"
            "    pip install piper-tts\n\n"
            "After installing, the speak tool will auto-detect it."
        )

    try:
        if backend == "piper":
            # Piper needs piping through aplay
            if not shutil.which("aplay"):
                return "piper found but aplay not available. Install: sudo apt install alsa-utils"
            piper_proc = subprocess.Popen(
                ["piper", "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            subprocess.Popen(
                ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-"],
                stdin=piper_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            piper_proc.stdin.write(text.encode())
            piper_proc.stdin.close()
            return f"Speaking ({backend}, {len(text)} chars)"
        else:
            cmd = _build_cmd(backend, text, speed, pitch)
            if not cmd:
                return f"Failed to build command for {backend}"
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            opts = []
            if speed:
                opts.append(f"speed={speed}")
            if pitch:
                opts.append(f"pitch={pitch}")
            opts_str = f" ({', '.join(opts)})" if opts else ""
            return f"Speaking ({backend}{opts_str}, {len(text)} chars)"

    except Exception as e:
        return f"speak error: {e}"
