"""BOLT custom tool — YouTube utilities via yt-dlp.

Requires yt-dlp to be installed (gracefully degrades if missing).
All downloads go to ~/Downloads/. Uses subprocess for yt-dlp calls.
Timeout: 120s per operation. No sudo, no root ops.
"""

import os
import re
import subprocess

TOOL_NAME = "youtube"
TOOL_DESC = (
    "YouTube utilities via yt-dlp. "
    'Usage: <tool name="youtube">info https://youtube.com/watch?v=...</tool> — video info | '
    '<tool name="youtube">audio https://youtube.com/watch?v=...</tool> — download audio | '
    '<tool name="youtube">transcript https://youtube.com/watch?v=...</tool> — get subtitles | '
    '<tool name="youtube">search python tutorial</tool> — search top 5'
)

HOME = "/home/mobilenode"
DOWNLOAD_DIR = os.path.join(HOME, "Downloads")
TIMEOUT = 120

# URL validation — allow YouTube and common short URLs
URL_RE = re.compile(
    r"^https?://(www\.)?(youtube\.com|youtu\.be|m\.youtube\.com|music\.youtube\.com)/?"
)
# Broader URL pattern for direct video URLs
VIDEO_URL_RE = re.compile(r"^https?://")


def _ensure_download_dir():
    """Ensure ~/Downloads/ exists."""
    real = os.path.realpath(DOWNLOAD_DIR)
    if not real.startswith(HOME):
        return f"Download dir escapes home: {real}"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    return None


def _check_ytdlp():
    """Check if yt-dlp is installed. Returns (path, error_string)."""
    try:
        result = subprocess.run(
            ["which", "yt-dlp"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), None
    except Exception:
        pass

    # Also check pip-installed location
    local_bin = os.path.join(HOME, ".local", "bin", "yt-dlp")
    if os.path.isfile(local_bin) and os.access(local_bin, os.X_OK):
        return local_bin, None

    return None, (
        "yt-dlp is not installed.\n"
        "Install it with: pip install yt-dlp\n"
        "Or: pipx install yt-dlp"
    )


def _run_ytdlp(args_list, timeout=TIMEOUT):
    """Run yt-dlp with given args. Returns (stdout, stderr, returncode)."""
    ytdlp, err = _check_ytdlp()
    if err:
        return None, err, -1

    cmd = [ytdlp] + args_list

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=DOWNLOAD_DIR,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return None, f"yt-dlp timed out after {timeout}s", -1
    except Exception as e:
        return None, f"yt-dlp execution error: {e}", -1


def _validate_url(url):
    """Basic URL validation. Returns cleaned URL or error string."""
    if not url:
        return None, "No URL provided."
    url = url.strip()
    if not VIDEO_URL_RE.match(url):
        return None, f"Invalid URL: {url} — must start with http:// or https://"
    # Basic sanitization — no shell metacharacters
    if any(c in url for c in (";", "|", "&", "`", "$", "(", ")", "{", "}")):
        return None, f"Invalid URL: contains shell metacharacters."
    return url, None


def _cmd_info(rest):
    """Get video info: title, duration, channel, description."""
    url, err = _validate_url(rest)
    if err:
        return f"Usage: info <url>\n{err}"

    stdout, stderr, rc = _run_ytdlp([
        "--no-download",
        "--print", "%(title)s\n%(duration_string)s\n%(channel)s\n%(upload_date)s\n%(view_count)s\n%(like_count)s\n%(description)s",
        "--no-warnings",
        url,
    ])

    if rc != 0:
        error_msg = stderr.strip() if stderr else "unknown error"
        return f"Failed to get video info: {error_msg}"

    lines = stdout.strip().split("\n") if stdout else []
    if len(lines) < 4:
        return f"Unexpected output format:\n{stdout}"

    title = lines[0] if lines[0] != "NA" else "(unknown)"
    duration = lines[1] if len(lines) > 1 and lines[1] != "NA" else "(unknown)"
    channel = lines[2] if len(lines) > 2 and lines[2] != "NA" else "(unknown)"
    upload_date = lines[3] if len(lines) > 3 and lines[3] != "NA" else "(unknown)"
    views = lines[4] if len(lines) > 4 and lines[4] != "NA" else "(unknown)"
    likes = lines[5] if len(lines) > 5 and lines[5] != "NA" else "(unknown)"
    description = "\n".join(lines[6:]) if len(lines) > 6 else "(no description)"

    # Format upload date
    if upload_date and len(upload_date) == 8 and upload_date.isdigit():
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

    # Format view count
    try:
        views_int = int(views)
        if views_int >= 1_000_000:
            views = f"{views_int / 1_000_000:.1f}M"
        elif views_int >= 1_000:
            views = f"{views_int / 1_000:.1f}K"
    except (ValueError, TypeError):
        pass

    # Truncate description
    if len(description) > 500:
        description = description[:500] + "..."

    return (
        f"Title:    {title}\n"
        f"Channel:  {channel}\n"
        f"Duration: {duration}\n"
        f"Uploaded: {upload_date}\n"
        f"Views:    {views}\n"
        f"Likes:    {likes}\n"
        f"\nDescription:\n{description}"
    )


def _cmd_audio(rest):
    """Download audio only to ~/Downloads/."""
    url, err = _validate_url(rest)
    if err:
        return f"Usage: audio <url>\n{err}"

    dir_err = _ensure_download_dir()
    if dir_err:
        return dir_err

    stdout, stderr, rc = _run_ytdlp([
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "--no-playlist",
        "--restrict-filenames",
        url,
    ])

    if rc != 0:
        error_msg = stderr.strip() if stderr else "unknown error"
        # Check for common issues
        if "ffmpeg" in error_msg.lower() or "ffprobe" in error_msg.lower():
            return (
                f"Audio download failed — ffmpeg may not be installed.\n"
                f"Install: sudo apt install ffmpeg\n"
                f"Error: {error_msg[:300]}"
            )
        return f"Audio download failed: {error_msg[:500]}"

    # Try to find the downloaded file in the output
    output = (stdout or "") + "\n" + (stderr or "")
    downloaded_file = None
    for line in output.splitlines():
        if "Destination:" in line:
            downloaded_file = line.split("Destination:", 1)[1].strip()
        elif "[ExtractAudio]" in line and "Destination:" in line:
            downloaded_file = line.split("Destination:", 1)[1].strip()
        elif "has already been downloaded" in line:
            return f"Audio already downloaded.\n{line}"

    result = "Audio download complete."
    if downloaded_file:
        result += f"\nSaved to: {downloaded_file}"
    else:
        result += f"\nSaved to: {DOWNLOAD_DIR}/"

    return result


def _cmd_transcript(rest):
    """Download subtitles/transcript if available."""
    url, err = _validate_url(rest)
    if err:
        return f"Usage: transcript <url>\n{err}"

    dir_err = _ensure_download_dir()
    if dir_err:
        return dir_err

    # First try auto-generated subtitles, then manual
    stdout, stderr, rc = _run_ytdlp([
        "--skip-download",
        "--write-auto-sub",
        "--write-sub",
        "--sub-lang", "en",
        "--sub-format", "srt/vtt/best",
        "--convert-subs", "srt",
        "-o", os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "--restrict-filenames",
        "--no-playlist",
        url,
    ])

    output = (stdout or "") + "\n" + (stderr or "")

    # Check if subtitles were found
    sub_file = None
    for line in output.splitlines():
        if "Writing video subtitles" in line or "Destination:" in line:
            if ".srt" in line or ".vtt" in line:
                parts = line.split("Destination:", 1)
                if len(parts) > 1:
                    sub_file = parts[1].strip()

    if rc != 0 and not sub_file:
        if "no subtitles" in output.lower() or "subtitles are disabled" in output.lower():
            return "No subtitles or transcript available for this video."
        return f"Transcript download failed: {(stderr or stdout or 'unknown error')[:500]}"

    # Try to read the subtitle file if we found it
    if sub_file and os.path.isfile(sub_file):
        try:
            with open(sub_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # Clean up SRT formatting for readability
            lines = []
            for line in content.splitlines():
                line = line.strip()
                # Skip SRT sequence numbers and timestamps
                if re.match(r"^\d+$", line):
                    continue
                if re.match(r"^\d{2}:\d{2}:\d{2}", line):
                    continue
                if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                    continue
                if line:
                    # Remove HTML-like tags
                    line = re.sub(r"<[^>]+>", "", line)
                    if line:
                        lines.append(line)

            # Deduplicate consecutive identical lines (common in auto-subs)
            deduped = []
            prev = ""
            for line in lines:
                if line != prev:
                    deduped.append(line)
                    prev = line

            transcript = "\n".join(deduped)
            if len(transcript) > 3000:
                transcript = transcript[:3000] + "\n... (truncated, full file saved)"

            return f"Transcript:\n\n{transcript}\n\nSaved to: {sub_file}"
        except Exception as e:
            return f"Transcript downloaded to {sub_file} but couldn't read it: {e}"

    # Look for any .srt files that might have been created
    try:
        srt_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".srt")]
        if srt_files:
            newest = max(srt_files, key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)))
            return f"Transcript saved to: {os.path.join(DOWNLOAD_DIR, newest)}"
    except Exception:
        pass

    if "no subtitles" in output.lower():
        return "No subtitles or transcript available for this video."

    return f"Transcript operation completed but no subtitle file found.\nOutput: {output[:500]}"


def _cmd_search(query):
    """Search YouTube and return top 5 results."""
    if not query:
        return "Usage: search <query>\nExample: search python async tutorial"

    stdout, stderr, rc = _run_ytdlp([
        f"ytsearch5:{query}",
        "--print", "%(title)s ||| %(id)s ||| %(duration_string)s ||| %(channel)s",
        "--no-download",
        "--no-warnings",
        "--flat-playlist",
    ], timeout=30)

    if rc != 0:
        error_msg = stderr.strip() if stderr else "unknown error"
        return f"Search failed: {error_msg[:300]}"

    if not stdout or not stdout.strip():
        return f"No results found for: {query}"

    lines = stdout.strip().splitlines()
    results = []
    for i, line in enumerate(lines[:5], 1):
        parts = line.split(" ||| ")
        if len(parts) >= 4:
            title = parts[0]
            vid_id = parts[1]
            duration = parts[2] if parts[2] != "NA" else "?"
            channel = parts[3] if parts[3] != "NA" else "?"
            url = f"https://youtube.com/watch?v={vid_id}"
            results.append(
                f"  [{i}] {title}\n"
                f"      Channel: {channel}  Duration: {duration}\n"
                f"      {url}"
            )
        elif len(parts) >= 2:
            title = parts[0]
            vid_id = parts[1]
            url = f"https://youtube.com/watch?v={vid_id}"
            results.append(f"  [{i}] {title}\n      {url}")
        else:
            results.append(f"  [{i}] {line}")

    header = f'Search results for "{query}":'
    return header + "\n\n" + "\n\n".join(results)


def run(args):
    """YouTube utilities via yt-dlp.

    Args: 'info <url>' | 'audio <url>' | 'transcript <url>' | 'search <query>'
    """
    raw = args.strip() if args else ""

    if not raw:
        return (
            "YouTube tool (requires yt-dlp). Commands:\n"
            "  info <url>        — video title, duration, channel, description\n"
            "  audio <url>       — download audio to ~/Downloads/ (mp3)\n"
            "  transcript <url>  — download subtitles/transcript\n"
            "  search <query>    — search YouTube, top 5 results"
        )

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd == "info":
            return _cmd_info(rest)
        elif cmd == "audio" or cmd == "dl" or cmd == "download":
            return _cmd_audio(rest)
        elif cmd == "transcript" or cmd == "subs" or cmd == "subtitles" or cmd == "captions":
            return _cmd_transcript(rest)
        elif cmd == "search" or cmd == "find":
            return _cmd_search(rest)
        else:
            # Maybe the first arg is a URL — default to info
            if VIDEO_URL_RE.match(raw):
                return _cmd_info(raw)
            return (
                f"Unknown command: {cmd}\n"
                "Valid commands: info, audio, transcript, search"
            )
    except Exception as e:
        return f"youtube tool error: {e}"
