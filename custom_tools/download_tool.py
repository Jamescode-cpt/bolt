"""BOLT custom tool — file downloader with progress info.

Downloads files from HTTP/HTTPS URLs to ~/Downloads/.
Shows file size, download speed, and final path.
Uses only stdlib (urllib.request).
"""

import os
import re
import time


def _is_internal_url(url):
    """Block requests to internal/private networks."""
    import socket
    import ipaddress
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        # Resolve hostname to IP
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
            # Block cloud metadata endpoints
            if str(ip) == '169.254.169.254':
                return True
    except Exception:
        return True  # Block on resolution failure
    return False


TOOL_NAME = "download"
TOOL_DESC = (
    "Download files from the web. "
    'Usage: <tool name="download">https://example.com/file.zip</tool> — '
    "downloads to ~/Downloads/ with auto-detected filename. "
    '<tool name="download">https://example.com/file.zip myfile.zip</tool> — '
    "download with custom filename. "
    '<tool name="download">list</tool> — list recent downloads.'
)

DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
TIMEOUT = 120
ALLOWED_SCHEMES = ("http://", "https://")
SAFE_PATH_PREFIX = "/home/mobilenode/"

# Extensions that should never be downloaded to executable-ish locations
DANGEROUS_EXTENSIONS = {
    ".sh", ".bash", ".zsh", ".fish",
    ".exe", ".bat", ".cmd", ".com", ".msi",
    ".ps1", ".psm1", ".psd1",
    ".run", ".bin", ".elf",
    ".desktop", ".service",
    ".cron", ".crontab",
}


def _sanitize_filename(name):
    """Remove path traversal and special characters from a filename."""
    # Strip any directory components
    name = os.path.basename(name)
    # Remove path traversal
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    # Keep only safe characters: alphanumeric, dash, underscore, dot
    name = re.sub(r'[^\w.\-]', '_', name)
    # Remove leading dots (hidden files)
    name = name.lstrip(".")
    # Fallback if empty
    if not name:
        name = f"download_{int(time.time())}"
    # Truncate very long names
    if len(name) > 200:
        name = name[:200]
    return name


def _validate_path(filepath):
    """Ensure the resolved path is under /home/mobilenode/."""
    real = os.path.realpath(filepath)
    if not real.startswith(SAFE_PATH_PREFIX):
        return False, f"Path escapes allowed directory: {real}"
    return True, real


def _format_size(size_bytes):
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _detect_filename(url, headers):
    """Detect filename from Content-Disposition header or URL path."""
    # Try Content-Disposition first
    cd = headers.get("Content-Disposition", "")
    if cd:
        # Look for filename="..." or filename=...
        match = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';]+)', cd, re.IGNORECASE)
        if match:
            return _sanitize_filename(match.group(1))

    # Fall back to URL path
    try:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(url)
        path = unquote(parsed.path)
        basename = os.path.basename(path)
        if basename and "." in basename:
            return _sanitize_filename(basename)
    except Exception:
        pass

    # Last resort: timestamp-based name
    return f"download_{int(time.time())}"


def _check_dangerous_location(filepath, ext):
    """Block dangerous extensions in executable locations."""
    ext_lower = ext.lower()
    if ext_lower in DANGEROUS_EXTENSIONS:
        # Check if target is in a PATH directory or common executable location
        parent = os.path.dirname(os.path.realpath(filepath))
        path_dirs = os.environ.get("PATH", "").split(":")
        for pdir in path_dirs:
            try:
                if os.path.realpath(pdir) == parent:
                    return False, f"Refusing to download {ext_lower} file to PATH directory: {parent}"
            except Exception:
                continue
    return True, ""


def _do_download(url, custom_filename=None):
    """Perform the actual download."""
    import urllib.request
    import urllib.error

    # Validate URL scheme
    url_lower = url.lower()
    if not any(url_lower.startswith(s) for s in ALLOWED_SCHEMES):
        return f"Blocked URL scheme. Only http:// and https:// are allowed. Got: {url}"

    # SSRF protection — block internal/private IPs
    if _is_internal_url(url):
        return "Blocked: cannot fetch from internal/private network addresses."

    # Create download directory
    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    except Exception as e:
        return f"Cannot create download directory {DOWNLOAD_DIR}: {e}"

    # Start the request
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BOLT/1.0; +local)",
        })
        response = urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        return f"HTTP error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return f"URL error: {e.reason}"
    except Exception as e:
        return f"Connection error: {e}"

    # Check Content-Length before downloading
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            size = int(content_length)
            if size > MAX_FILE_SIZE:
                response.close()
                return (
                    f"File too large: {_format_size(size)}. "
                    f"Maximum allowed: {_format_size(MAX_FILE_SIZE)}."
                )
        except ValueError:
            pass

    # Determine filename
    if custom_filename:
        filename = _sanitize_filename(custom_filename)
    else:
        filename = _detect_filename(url, response.headers)

    # Get extension for safety check
    _, ext = os.path.splitext(filename)
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    # Validate final path
    ok, result = _validate_path(filepath)
    if not ok:
        response.close()
        return result

    # Check dangerous extensions in executable locations
    ok, msg = _check_dangerous_location(filepath, ext)
    if not ok:
        response.close()
        return msg

    # Avoid overwriting: append number if file exists
    base_filepath = filepath
    counter = 1
    while os.path.exists(filepath):
        name_part, ext_part = os.path.splitext(base_filepath)
        filepath = f"{name_part}_{counter}{ext_part}"
        counter += 1

    # Download with progress tracking
    start_time = time.time()
    total_downloaded = 0
    chunk_size = 64 * 1024  # 64KB chunks

    try:
        with open(filepath, "wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                total_downloaded += len(chunk)

                # Enforce size limit during download (for chunked responses without Content-Length)
                if total_downloaded > MAX_FILE_SIZE:
                    f.close()
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                    response.close()
                    return (
                        f"Download aborted: exceeded {_format_size(MAX_FILE_SIZE)} limit "
                        f"(downloaded {_format_size(total_downloaded)} so far)."
                    )
    except Exception as e:
        # Clean up partial file
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass
        response.close()
        return f"Download failed: {e}"

    response.close()

    # Calculate stats
    elapsed = time.time() - start_time
    if elapsed > 0:
        speed = total_downloaded / elapsed
        speed_str = f"{_format_size(int(speed))}/s"
    else:
        speed_str = "instant"

    return (
        f"Download complete!\n"
        f"  File: {filepath}\n"
        f"  Size: {_format_size(total_downloaded)}\n"
        f"  Time: {elapsed:.1f}s\n"
        f"  Speed: {speed_str}"
    )


def _list_downloads():
    """List recent files in ~/Downloads/, sorted by modification time."""
    if not os.path.isdir(DOWNLOAD_DIR):
        return f"Download directory does not exist: {DOWNLOAD_DIR}"

    try:
        entries = []
        for name in os.listdir(DOWNLOAD_DIR):
            full = os.path.join(DOWNLOAD_DIR, name)
            if os.path.isfile(full):
                stat = os.stat(full)
                entries.append((name, stat.st_size, stat.st_mtime))

        if not entries:
            return f"No files in {DOWNLOAD_DIR}"

        # Sort by modification time, newest first
        entries.sort(key=lambda x: x[2], reverse=True)

        # Show most recent 25
        lines = [f"Recent downloads in {DOWNLOAD_DIR}:\n"]
        for name, size, mtime in entries[:25]:
            time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
            lines.append(f"  {time_str}  {_format_size(size):>10s}  {name}")

        if len(entries) > 25:
            lines.append(f"\n  ... and {len(entries) - 25} more files")

        lines.append(f"\n  Total: {len(entries)} files, {_format_size(sum(e[1] for e in entries))}")
        return "\n".join(lines)

    except Exception as e:
        return f"Error listing downloads: {e}"


def run(args):
    """Download a file or list recent downloads.

    Args is a string: URL [optional_filename] or 'list'.
    """
    args = (args or "").strip()

    if not args:
        return (
            "Usage:\n"
            '  <tool name="download">https://example.com/file.zip</tool>\n'
            '  <tool name="download">https://example.com/file.zip myfile.zip</tool>\n'
            '  <tool name="download">list</tool>'
        )

    # Handle 'list' command
    if args.lower() == "list":
        return _list_downloads()

    # Parse URL and optional filename
    parts = args.split(None, 1)
    url = parts[0]
    custom_filename = parts[1].strip() if len(parts) > 1 else None

    try:
        return _do_download(url, custom_filename)
    except Exception as e:
        return f"download error: {e}"
