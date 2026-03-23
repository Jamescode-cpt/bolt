"""BOLT custom tool — network information.

Cross-platform: Linux (/proc, ip) and macOS (airport, ifconfig).
Ping, WiFi signal, IPs via platform_utils.
"""

import os
import re
import socket
import subprocess
import sys

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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import get_wifi_info, get_interfaces, get_ping_cmd


def _wifi_info():
    return get_wifi_info()


def _ip_info():
    """Get local and public-facing IP addresses."""
    results = []

    # Local IP via socket trick (cross-platform)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        results.append(f"  Local IP: {local_ip}")
    except Exception:
        results.append("  Local IP: unavailable")

    # All interface IPs (cross-platform)
    ifaces = get_interfaces()
    if ifaces:
        results.append(ifaces)

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
        cmd = get_ping_cmd(host)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20,
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
