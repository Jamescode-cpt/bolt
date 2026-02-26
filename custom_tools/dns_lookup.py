"""
BOLT Custom Tool: DNS Lookup
Performs DNS lookups (A, AAAA, MX, NS) and reverse DNS using only the socket module.
Rate limited to prevent abuse. No external dependencies.
"""

import socket
import struct
import time
import os

TOOL_NAME = "dns"
TOOL_DESC = (
    "DNS lookup utility. Commands:\n"
    "  lookup <domain>  - query A, AAAA, MX, NS records for a domain\n"
    "  reverse <ip>     - reverse DNS lookup for an IP address"
)

# Rate limiting: max 10 lookups per 60 seconds
_rate_log = []
RATE_LIMIT = 10
RATE_WINDOW = 60  # seconds


def _check_rate_limit():
    """Enforce basic rate limiting."""
    now = time.time()
    # Prune old entries
    while _rate_log and _rate_log[0] < now - RATE_WINDOW:
        _rate_log.pop(0)
    if len(_rate_log) >= RATE_LIMIT:
        wait = int(_rate_log[0] + RATE_WINDOW - now) + 1
        raise RuntimeError(
            f"Rate limit reached ({RATE_LIMIT} lookups per {RATE_WINDOW}s). "
            f"Try again in {wait} seconds."
        )
    _rate_log.append(now)


def _validate_domain(domain):
    """Basic domain name validation."""
    domain = domain.strip().rstrip(".")
    if not domain:
        raise ValueError("Domain name cannot be empty.")
    if len(domain) > 253:
        raise ValueError("Domain name too long (max 253 characters).")
    # Basic character check
    for label in domain.split("."):
        if not label:
            raise ValueError(f"Invalid domain: empty label in '{domain}'.")
        if len(label) > 63:
            raise ValueError(f"Invalid domain: label '{label}' exceeds 63 characters.")
        if not all(c.isalnum() or c in "-_" for c in label):
            raise ValueError(f"Invalid domain: label '{label}' contains invalid characters.")
    return domain


def _validate_ip(ip):
    """Validate an IP address (v4 or v6)."""
    ip = ip.strip()
    if not ip:
        raise ValueError("IP address cannot be empty.")
    # Try parsing as IPv4
    try:
        socket.inet_aton(ip)
        return ip
    except socket.error:
        pass
    # Try parsing as IPv6
    try:
        socket.inet_pton(socket.AF_INET6, ip)
        return ip
    except (socket.error, OSError):
        pass
    raise ValueError(f"'{ip}' is not a valid IPv4 or IPv6 address.")


def _lookup_a(domain):
    """Get A (IPv4) records."""
    results = []
    try:
        infos = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
        seen = set()
        for info in infos:
            addr = info[4][0]
            if addr not in seen:
                seen.add(addr)
                results.append(addr)
    except socket.gaierror:
        pass
    return results


def _lookup_aaaa(domain):
    """Get AAAA (IPv6) records."""
    results = []
    try:
        infos = socket.getaddrinfo(domain, None, socket.AF_INET6, socket.SOCK_STREAM)
        seen = set()
        for info in infos:
            addr = info[4][0]
            if addr not in seen:
                seen.add(addr)
                results.append(addr)
    except socket.gaierror:
        pass
    return results


def _build_dns_query(domain, qtype):
    """Build a raw DNS query packet."""
    # Header: ID=0xBEEF, flags=0x0100 (standard query, recursion desired), 1 question
    header = struct.pack(">HHHHHH", 0xBEEF, 0x0100, 1, 0, 0, 0)

    # Question section
    question = b""
    for label in domain.split("."):
        encoded = label.encode("ascii")
        question += struct.pack("B", len(encoded)) + encoded
    question += b"\x00"  # null terminator

    # QTYPE and QCLASS (IN = 1)
    qtypes = {"A": 1, "AAAA": 28, "MX": 15, "NS": 2, "PTR": 12}
    question += struct.pack(">HH", qtypes.get(qtype, 1), 1)

    return header + question


def _parse_name(data, offset):
    """Parse a DNS name from raw packet data, handling compression pointers."""
    labels = []
    jumped = False
    original_offset = offset
    max_jumps = 20
    jumps = 0

    while True:
        if offset >= len(data):
            break
        length = data[offset]

        if (length & 0xC0) == 0xC0:
            # Compression pointer
            if offset + 1 >= len(data):
                break
            pointer = struct.unpack(">H", data[offset:offset + 2])[0] & 0x3FFF
            if not jumped:
                original_offset = offset + 2
            offset = pointer
            jumped = True
            jumps += 1
            if jumps > max_jumps:
                break
            continue

        if length == 0:
            offset += 1
            break

        offset += 1
        if offset + length > len(data):
            break
        labels.append(data[offset:offset + length].decode("ascii", errors="replace"))
        offset += length

    name = ".".join(labels)
    return name, original_offset if jumped else offset


def _dns_query_udp(domain, qtype, server="8.8.8.8"):
    """Send a DNS query over UDP and parse the response."""
    query = _build_dns_query(domain, qtype)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    try:
        sock.sendto(query, (server, 53))
        data, _ = sock.recvfrom(4096)
    except socket.timeout:
        return []
    except OSError:
        return []
    finally:
        sock.close()

    if len(data) < 12:
        return []

    # Parse header
    _, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    rcode = flags & 0x0F
    if rcode != 0:
        return []

    # Skip questions
    offset = 12
    for _ in range(qdcount):
        _, offset = _parse_name(data, offset)
        offset += 4  # QTYPE + QCLASS

    # Parse answers
    results = []
    qtypes_map = {"A": 1, "AAAA": 28, "MX": 15, "NS": 2, "PTR": 12}
    target_qtype = qtypes_map.get(qtype, 1)

    for _ in range(ancount):
        if offset >= len(data):
            break
        name, offset = _parse_name(data, offset)

        if offset + 10 > len(data):
            break
        rtype, rclass, ttl, rdlength = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10

        if offset + rdlength > len(data):
            break

        if rtype == target_qtype:
            rdata_start = offset
            if qtype == "A" and rdlength == 4:
                ip = socket.inet_ntoa(data[rdata_start:rdata_start + 4])
                results.append(ip)
            elif qtype == "AAAA" and rdlength == 16:
                ip = socket.inet_ntop(socket.AF_INET6, data[rdata_start:rdata_start + 16])
                results.append(ip)
            elif qtype == "MX" and rdlength >= 3:
                preference = struct.unpack(">H", data[rdata_start:rdata_start + 2])[0]
                mx_name, _ = _parse_name(data, rdata_start + 2)
                results.append(f"{preference} {mx_name}")
            elif qtype == "NS":
                ns_name, _ = _parse_name(data, rdata_start)
                results.append(ns_name)
            elif qtype == "PTR":
                ptr_name, _ = _parse_name(data, rdata_start)
                results.append(ptr_name)

        offset = offset + rdlength if offset + rdlength > offset else offset + rdlength

    return results


def _cmd_lookup(domain):
    """Full DNS lookup for a domain: A, AAAA, MX, NS."""
    if not domain.strip():
        return "Error: provide a domain name. Example: lookup example.com"

    domain = _validate_domain(domain)
    _check_rate_limit()

    lines = [f"DNS Lookup: {domain}", "=" * 50]

    # A records (use socket for reliability, fall back to raw query)
    a_records = _lookup_a(domain)
    if not a_records:
        # Try raw DNS query as fallback
        a_records = _dns_query_udp(domain, "A")
    lines.append(f"\n  A Records (IPv4):")
    if a_records:
        for r in a_records:
            lines.append(f"    {r}")
    else:
        lines.append("    (none)")

    # AAAA records
    aaaa_records = _lookup_aaaa(domain)
    if not aaaa_records:
        aaaa_records = _dns_query_udp(domain, "AAAA")
    lines.append(f"\n  AAAA Records (IPv6):")
    if aaaa_records:
        for r in aaaa_records:
            lines.append(f"    {r}")
    else:
        lines.append("    (none)")

    # MX records (raw DNS query)
    mx_records = _dns_query_udp(domain, "MX")
    lines.append(f"\n  MX Records (Mail):")
    if mx_records:
        for r in sorted(mx_records, key=lambda x: int(x.split()[0]) if x.split()[0].isdigit() else 0):
            lines.append(f"    {r}")
    else:
        lines.append("    (none)")

    # NS records (raw DNS query)
    ns_records = _dns_query_udp(domain, "NS")
    lines.append(f"\n  NS Records (Nameservers):")
    if ns_records:
        for r in sorted(ns_records):
            lines.append(f"    {r}")
    else:
        lines.append("    (none)")

    return "\n".join(lines)


def _cmd_reverse(ip):
    """Reverse DNS lookup for an IP address."""
    if not ip.strip():
        return "Error: provide an IP address. Example: reverse 8.8.8.8"

    ip = _validate_ip(ip)
    _check_rate_limit()

    lines = [f"Reverse DNS: {ip}", "=" * 50]

    # Method 1: socket.gethostbyaddr
    try:
        hostname, aliases, addrs = socket.gethostbyaddr(ip)
        lines.append(f"\n  Hostname: {hostname}")
        if aliases:
            lines.append(f"  Aliases:  {', '.join(aliases)}")
        if addrs:
            lines.append(f"  Addresses: {', '.join(addrs)}")
    except socket.herror as e:
        lines.append(f"\n  gethostbyaddr: No PTR record ({e})")
    except socket.gaierror as e:
        lines.append(f"\n  gethostbyaddr: Lookup failed ({e})")

    # Method 2: raw PTR query
    try:
        # Build reverse domain
        if ":" in ip:
            # IPv6 — expand and reverse nibbles
            expanded = socket.inet_pton(socket.AF_INET6, ip)
            hex_str = expanded.hex()
            ptr_domain = ".".join(reversed(hex_str)) + ".ip6.arpa"
        else:
            # IPv4 — reverse octets
            parts = ip.split(".")
            ptr_domain = ".".join(reversed(parts)) + ".in-addr.arpa"

        ptr_records = _dns_query_udp(ptr_domain, "PTR")
        if ptr_records:
            lines.append(f"\n  PTR Record(s):")
            for r in ptr_records:
                lines.append(f"    {r}")
    except Exception:
        pass  # Raw query is best-effort

    return "\n".join(lines)


def run(args):
    """Entry point called by BOLT tool system."""
    try:
        args = (args or "").strip()
        parts = args.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "lookup":
            return _cmd_lookup(rest)
        elif cmd == "reverse":
            return _cmd_reverse(rest)
        else:
            return (
                f"Unknown command: '{cmd}'\n"
                "Available: lookup <domain>, reverse <ip>"
            )
    except ValueError as e:
        return f"Input error: {e}"
    except RuntimeError as e:
        return f"DNS error: {e}"
    except Exception as e:
        return f"DNS tool error: {type(e).__name__}: {e}"
