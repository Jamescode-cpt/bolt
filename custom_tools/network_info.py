"""BOLT custom tool — network information.

WiFi signal from /proc/net/wireless, IPs via socket/ip addr,
ping via subprocess. Host validated with regex (no injection).
"""

import os
import re
import socket
import subprocess

TOOL_NAME = "network"
TOOL_DESC = (
    "Network info: WiFi, IPs, ping. "
    'Usage: <tool name="network">all</tool> or '
    '<tool name="network">wifi</tool> or '
    '<tool name="network">ip</tool> or '
    '<tool name="network">ping 8.8.8.8</tool>'
)

# Only allow hostnames/IPs — no shell injection
HOST_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _wifi_info():
    """Read WiFi info from /proc/net/wireless."""
    try:
        with open("/proc/net/wireless", "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return "No wireless interface found (/proc/net/wireless missing)"
    except Exception as e:
        return f"WiFi read error: {e}"

    # Skip first 2 header lines
    data_lines = [l.strip() for l in lines[2:] if l.strip()]
    if not data_lines:
        return "No wireless interfaces active"

    results = []
    for line in data_lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        iface = parts[0].rstrip(":")
        # Quality is in column 2, signal level in column 3
        quality = parts[2].rstrip(".")
        signal = parts[3].rstrip(".")
        results.append(f"  {iface}: quality={quality} signal={signal} dBm")

    if not results:
        return "No wireless data available"
    return "WiFi:\n" + "\n".join(results)


def _ip_info():
    """Get local and public-facing IP addresses."""
    results = []

    # Local IP via socket trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        results.append(f"  Local IP: {local_ip}")
    except Exception:
        results.append("  Local IP: unavailable")

    # All interface IPs via ip addr
    try:
        out = subprocess.run(
            ["ip", "-brief", "addr"], capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            results.append("  Interfaces:")
            for line in out.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    iface = parts[0]
                    state = parts[1]
                    addrs = " ".join(parts[2:])
                    results.append(f"    {iface} ({state}): {addrs}")
    except Exception:
        pass

    return "IPs:\n" + "\n".join(results) if results else "IP info unavailable"


def _ping(host):
    """Ping a host (3 packets)."""
    if not host:
        return "No host provided. Usage: ping <hostname or IP>"
    if not HOST_RE.match(host):
        return f"Invalid host: {host} — only alphanumeric, dots, hyphens allowed."
    if len(host) > 253:
        return "Host too long (max 253 chars)"

    try:
        result = subprocess.run(
            ["ping", "-c", "3", "-W", "5", host],
            capture_output=True, text=True, timeout=20,
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += "\n" + result.stderr.strip()
        return output if output else f"ping {host}: no output (exit {result.returncode})"
    except subprocess.TimeoutExpired:
        return f"Ping to {host} timed out (20s)"
    except FileNotFoundError:
        return "ping command not found"
    except Exception as e:
        return f"Ping error: {e}"


def run(args):
    """Get network information.

    Args: 'all', 'wifi', 'ip', or 'ping <host>'.
    """
    raw = args.strip().lower() if args else "all"

    try:
        if raw == "all":
            parts = [_wifi_info(), _ip_info()]
            return "\n\n".join(parts)
        elif raw == "wifi":
            return _wifi_info()
        elif raw == "ip":
            return _ip_info()
        elif raw.startswith("ping"):
            host = raw.split(None, 1)[1] if " " in raw else ""
            return _ping(host.strip())
        else:
            return (
                'Unknown subcommand. Usage:\n'
                '  <tool name="network">all</tool>\n'
                '  <tool name="network">wifi</tool>\n'
                '  <tool name="network">ip</tool>\n'
                '  <tool name="network">ping 8.8.8.8</tool>'
            )
    except Exception as e:
        return f"network error: {e}"
