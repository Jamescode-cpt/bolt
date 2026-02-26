"""BOLT custom tool: lightweight port scanning and listening-port discovery."""

import ipaddress
import socket
import subprocess

TOOL_NAME = "ports"
TOOL_DESC = (
    "Port scanning and listener discovery.\n"
    "  scan <host>             - scan common ports on a host\n"
    "  check <host> <port>     - check if a specific port is open\n"
    "  listening                - show listening ports on this machine (ss)"
)

COMMON_PORTS = [
    21, 22, 25, 53, 80, 443, 1433, 3000, 3306, 5000, 5432,
    5900, 6379, 8000, 8080, 8443, 8888, 9090, 11434, 27017,
]

SCAN_TIMEOUT = 1.0  # seconds per port


def _is_local_or_lan(host):
    """
    Only allow scanning of localhost, loopback, link-local, and private/LAN IPs.
    Returns True if allowed, False otherwise.
    """
    # Always allow localhost by name
    if host.lower() in ("localhost", "127.0.0.1", "::1"):
        return True

    try:
        # Resolve hostname to IP first
        info = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _type, _proto, _canonname, sockaddr in info:
            ip_str = sockaddr[0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_loopback or addr.is_private or addr.is_link_local:
                return True
        # If none of the resolved addresses are local/private, deny
        return False
    except (socket.gaierror, ValueError):
        return False


def _check_port(host, port, timeout=SCAN_TIMEOUT):
    """Try to connect to host:port. Returns True if open, False otherwise."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _scan(host):
    """Scan common ports on a host."""
    host = host.strip()
    if not host:
        return "Error: provide a host to scan."

    if not _is_local_or_lan(host):
        return (
            f"DENIED: '{host}' does not resolve to a local or LAN address.\n"
            "Only localhost and private/LAN IPs are allowed."
        )

    lines = [f"Scanning {host} ({len(COMMON_PORTS)} common ports, {SCAN_TIMEOUT}s timeout)...", ""]
    open_ports = []
    closed_count = 0

    for port in sorted(COMMON_PORTS):
        if _check_port(host, port):
            try:
                service = socket.getservbyport(port, "tcp")
            except OSError:
                service = "unknown"
            open_ports.append((port, service))
        else:
            closed_count += 1

    if open_ports:
        lines.append("Open ports:")
        for port, service in open_ports:
            lines.append(f"  {port:>5}/tcp  open  {service}")
    else:
        lines.append("No open ports found.")

    lines.append(f"\n{len(open_ports)} open, {closed_count} closed")
    return "\n".join(lines)


def _check(host, port_str):
    """Check if a specific port is open on a host."""
    host = host.strip()
    if not host:
        return "Error: provide a host."

    if not _is_local_or_lan(host):
        return (
            f"DENIED: '{host}' does not resolve to a local or LAN address.\n"
            "Only localhost and private/LAN IPs are allowed."
        )

    try:
        port = int(port_str.strip())
        if not (1 <= port <= 65535):
            raise ValueError
    except (ValueError, AttributeError):
        return f"Error: invalid port '{port_str}'. Must be 1-65535."

    is_open = _check_port(host, port)
    try:
        service = socket.getservbyport(port, "tcp")
    except OSError:
        service = "unknown"

    state = "OPEN" if is_open else "CLOSED"
    return f"{host}:{port} ({service}) - {state}"


def _listening():
    """Show listening TCP sockets on this machine."""
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        err = result.stderr.strip()
        if output:
            return output
        if err:
            return f"Error from ss: {err}"
        return "No listening TCP sockets found."
    except FileNotFoundError:
        # Fallback to netstat if ss not available
        try:
            result = subprocess.run(
                ["netstat", "-tlnp"],
                capture_output=True, text=True, timeout=10
            )
            output = result.stdout.strip()
            if output:
                return output
            return "No listening TCP sockets found."
        except FileNotFoundError:
            return "Error: neither 'ss' nor 'netstat' found on this system."
    except subprocess.TimeoutExpired:
        return "Error: command timed out."


def run(args):
    """Entry point called by BOLT tool loop."""
    args = (args or "").strip()
    if not args:
        return "Usage:\n" + TOOL_DESC

    parts = args.split(None, 2)
    command = parts[0].lower()

    if command == "scan":
        if len(parts) < 2:
            return "Error: provide a host.  Usage: scan <host>"
        return _scan(parts[1])

    if command == "check":
        if len(parts) < 3:
            return "Error: provide host and port.  Usage: check <host> <port>"
        return _check(parts[1], parts[2])

    if command == "listening":
        return _listening()

    return f"Unknown subcommand: '{command}'\n\n{TOOL_DESC}"
