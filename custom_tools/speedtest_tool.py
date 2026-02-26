"""BOLT custom tool — internet speed test.

Tries speedtest-cli first, falls back to timed HTTP download from a CDN.
Uses subprocess for speedtest-cli, urllib for fallback. No hard external deps.
"""

import time

TOOL_NAME = "speedtest"
TOOL_DESC = (
    "Internet speed test (download, upload, ping). "
    'Usage: <tool name="speedtest">run</tool> — full test | '
    '<tool name="speedtest">download</tool> — download only | '
    '<tool name="speedtest">ping</tool> — latency only'
)

# Fallback download URLs — large files from public CDNs
# Ordered by preference; try each until one works
FALLBACK_URLS = [
    # ~10MB test file from Cloudflare
    ("https://speed.cloudflare.com/__down?bytes=10000000", 10_000_000, "Cloudflare"),
    # ~10MB from Hetzner speed test
    ("https://speed.hetzner.de/10MB.bin", 10_000_000, "Hetzner"),
    # ~5MB fallback
    ("https://proof.ovh.net/files/5Mb.dat", 5_000_000, "OVH"),
]


def _try_speedtest_cli(mode="full"):
    """Try running speedtest-cli. Returns (result_string, success_bool)."""
    import subprocess

    # Check if speedtest-cli is available
    try:
        result = subprocess.run(
            ["which", "speedtest-cli"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None, False
    except Exception:
        return None, False

    # Build command based on mode
    cmd = ["speedtest-cli", "--simple"]
    if mode == "download":
        cmd.append("--no-upload")
    elif mode == "ping":
        # speedtest-cli doesn't have a ping-only mode, we'll parse the output
        pass

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip()
            if mode == "ping":
                # Extract just the ping line
                for line in output.splitlines():
                    if line.lower().startswith("ping"):
                        return line, True
                return output, True
            return output, True
        else:
            err = result.stderr.strip() if result.stderr else "no output"
            return f"speedtest-cli failed: {err}", False
    except subprocess.TimeoutExpired:
        return "speedtest-cli timed out (120s)", False
    except Exception as e:
        return f"speedtest-cli error: {e}", False


def _try_speedtest_lib(mode="full"):
    """Try using the speedtest Python library. Returns (result_string, success_bool)."""
    try:
        import speedtest as st_lib
    except ImportError:
        return None, False

    try:
        s = st_lib.Speedtest()
        s.get_best_server()
        lines = []

        ping_ms = s.results.ping
        lines.append(f"Ping: {ping_ms:.2f} ms")

        if mode in ("full", "download"):
            s.download()
            dl_mbps = s.results.download / 1_000_000
            lines.append(f"Download: {dl_mbps:.2f} Mbps")

        if mode == "full":
            s.upload()
            ul_mbps = s.results.upload / 1_000_000
            lines.append(f"Upload: {ul_mbps:.2f} Mbps")

        return "\n".join(lines), True
    except Exception as e:
        return f"speedtest library error: {e}", False


def _fallback_ping():
    """Measure latency by timing TCP connect to well-known hosts."""
    import socket

    hosts = [
        ("8.8.8.8", 53, "Google DNS"),
        ("1.1.1.1", 53, "Cloudflare DNS"),
        ("208.67.222.222", 53, "OpenDNS"),
    ]

    results = []
    for host, port, name in hosts:
        times = []
        for _ in range(3):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                start = time.time()
                sock.connect((host, port))
                elapsed = (time.time() - start) * 1000
                sock.close()
                times.append(elapsed)
            except Exception:
                times.append(None)

        valid = [t for t in times if t is not None]
        if valid:
            avg = sum(valid) / len(valid)
            results.append(f"  {name} ({host}): {avg:.1f} ms avg ({len(valid)}/3 success)")
        else:
            results.append(f"  {name} ({host}): unreachable")

    if results:
        return "Ping (TCP connect):\n" + "\n".join(results)
    return "Ping: all hosts unreachable — check your connection."


def _fallback_download():
    """Measure download speed by timing an HTTP download."""
    import urllib.request
    import urllib.error

    for url, expected_bytes, cdn_name in FALLBACK_URLS:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 BOLT-SpeedTest/1.0"
            })
            start = time.time()
            response = urllib.request.urlopen(req, timeout=60)

            total_bytes = 0
            chunk_size = 65536
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)

            elapsed = time.time() - start
            response.close()

            if elapsed <= 0 or total_bytes == 0:
                continue

            mbps = (total_bytes * 8) / (elapsed * 1_000_000)
            mb_downloaded = total_bytes / 1_000_000

            return (
                f"Download: {mbps:.2f} Mbps\n"
                f"  ({mb_downloaded:.1f} MB in {elapsed:.1f}s via {cdn_name})\n"
                f"  Note: fallback method — install speedtest-cli for full results"
            )
        except urllib.error.URLError as e:
            continue
        except Exception:
            continue

    return "Download: unable to reach any test server — check your connection."


def _cmd_run():
    """Full speed test: download + upload + ping."""
    # Try speedtest-cli first
    result, ok = _try_speedtest_cli("full")
    if ok:
        return f"Speed Test (via speedtest-cli):\n{result}"

    # Try speedtest Python library
    result, ok = _try_speedtest_lib("full")
    if ok:
        return f"Speed Test (via speedtest library):\n{result}"

    # Fallback: manual ping + download
    lines = ["Speed Test (fallback method):", ""]
    lines.append(_fallback_ping())
    lines.append("")
    lines.append(_fallback_download())
    lines.append("")
    lines.append("Upload: not available in fallback mode")
    lines.append("\nTip: Install speedtest-cli for full results: pip install speedtest-cli")
    return "\n".join(lines)


def _cmd_download():
    """Download speed only."""
    result, ok = _try_speedtest_cli("download")
    if ok:
        return f"Download Test (via speedtest-cli):\n{result}"

    result, ok = _try_speedtest_lib("download")
    if ok:
        return f"Download Test (via speedtest library):\n{result}"

    return _fallback_download()


def _cmd_ping():
    """Latency test only."""
    result, ok = _try_speedtest_cli("ping")
    if ok:
        return f"Ping (via speedtest-cli):\n{result}"

    # speedtest lib gives us ping too
    result, ok = _try_speedtest_lib("ping")  # This does ping as part of server selection
    if ok:
        return f"Ping (via speedtest library):\n{result}"

    return _fallback_ping()


def run(args):
    """Internet speed test. Args: 'run' (default) | 'download' | 'ping'"""
    raw = args.strip().lower() if args else "run"

    try:
        if raw in ("run", "full", "all", ""):
            return _cmd_run()
        elif raw in ("download", "dl", "down"):
            return _cmd_download()
        elif raw in ("ping", "latency"):
            return _cmd_ping()
        elif raw in ("upload", "ul", "up"):
            # Upload only available via speedtest-cli
            result, ok = _try_speedtest_cli("full")
            if ok:
                # Parse out upload line
                for line in result.splitlines():
                    if line.lower().startswith("upload"):
                        return f"Upload (via speedtest-cli):\n{line}"
                return f"Upload test:\n{result}"
            return "Upload test requires speedtest-cli. Install: pip install speedtest-cli"
        else:
            return (
                "Speed test commands:\n"
                "  run / full     — full speed test (download + upload + ping)\n"
                "  download / dl  — download speed only\n"
                "  ping           — latency only\n"
                "  upload / ul    — upload only (requires speedtest-cli)"
            )
    except Exception as e:
        return f"speedtest error: {e}"
