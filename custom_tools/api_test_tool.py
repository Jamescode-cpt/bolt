"""BOLT custom tool — REST API tester (mini Postman)."""

TOOL_NAME = "api"
TOOL_DESC = """REST API tester — send HTTP requests and inspect responses.
Commands:
  get <url>                                 — GET request
  post <url>\\n<json_body>                  — POST with JSON body
  put <url>\\n<json_body>                   — PUT with JSON body
  delete <url>                              — DELETE request
  headers <key: value\\nkey2: value2>\\n<method> <url>  — set custom headers for request
Examples:
  <tool name="api">get https://httpbin.org/get</tool>
  <tool name="api">post https://httpbin.org/post
{"name": "bolt", "type": "companion"}</tool>
  <tool name="api">headers Authorization: Bearer tok123
Content-Type: application/json
get https://api.example.com/data</tool>
  <tool name="api">delete https://httpbin.org/delete</tool>
Shows: status code, response time, headers, body (truncated to 3000 chars).
Safety: blocks localhost Ollama API, file:// URLs. Only http/https allowed.
Rate limited: 1 request per 2 seconds per domain."""

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


MAX_BODY = 3000
_domain_timestamps = {}  # domain -> last request time


def _get_domain(url):
    """Extract domain from URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.hostname or ""
    except Exception:
        return ""


def _rate_limit(domain):
    """Enforce 1 request per 2 seconds per domain."""
    global _domain_timestamps
    now = time.time()
    last = _domain_timestamps.get(domain, 0)
    elapsed = now - last
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed)
    _domain_timestamps[domain] = time.time()


def _validate_url(url):
    """Validate URL for safety. Returns (url, error)."""
    url = url.strip()

    if not url:
        return None, "No URL provided."

    # Only allow http and https
    if not url.startswith("http://") and not url.startswith("https://"):
        return None, "Only http:// and https:// URLs are allowed. Blocked: file://, ftp://, etc."

    # Block file:// (double check)
    if url.lower().startswith("file://"):
        return None, "file:// URLs are blocked for security."

    # Extract host for safety checks
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except Exception:
        return None, "Could not parse URL."

    # Block Ollama API (prevent model deletion, etc.)
    ollama_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    ollama_port = 11434
    if host in ollama_hosts and (port == ollama_port or f":{ollama_port}" in url):
        return None, "Blocked: requests to the local Ollama API are not allowed (safety measure)."

    # Also block Ollama-like paths on any localhost
    if host in ollama_hosts and "/api/" in parsed.path:
        # Be cautious with any localhost API paths
        if any(kw in parsed.path.lower() for kw in ["/api/delete", "/api/create", "/api/pull", "/api/push"]):
            return None, "Blocked: this localhost API endpoint looks like an Ollama management API."

    return url, None


def _truncate(text, limit=MAX_BODY):
    """Truncate text with a note."""
    if len(text) > limit:
        return text[:limit] + f"\n\n... [truncated — {limit} of {len(text)} chars shown]"
    return text


def _format_headers(headers, max_headers=15):
    """Format response headers for display (abbreviated)."""
    lines = []
    shown = 0
    for key, val in headers:
        if shown >= max_headers:
            lines.append(f"  ... and {len(headers) - max_headers} more headers")
            break
        # Truncate long header values
        val_str = str(val)
        if len(val_str) > 120:
            val_str = val_str[:120] + "..."
        lines.append(f"  {key}: {val_str}")
        shown += 1
    return "\n".join(lines)


def _do_request(method, url, body=None, custom_headers=None):
    """Execute an HTTP request and return formatted result."""
    import urllib.request
    import urllib.error
    import json

    # Validate URL
    url, err = _validate_url(url)
    if err:
        return err

    # SSRF protection — block internal/private IPs
    if _is_internal_url(url):
        return "Blocked: cannot fetch from internal/private network addresses."

    domain = _get_domain(url)
    _rate_limit(domain)

    # Build request
    data = None
    if body:
        if isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body

    req = urllib.request.Request(url, data=data, method=method.upper())

    # Default headers
    req.add_header("User-Agent", "BOLT-API-Tester/1.0")
    if body and "Content-Type" not in (custom_headers or {}):
        req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/plain, */*")

    # Custom headers
    if custom_headers:
        for key, val in custom_headers.items():
            req.add_header(key, val)

    # Execute
    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.time() - start_time
            status = resp.status
            reason = resp.reason
            resp_headers = resp.getheaders()
            body_bytes = resp.read()

            # Decode response body
            content_type = resp.headers.get("Content-Type", "")
            encoding = "utf-8"
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            try:
                resp_body = body_bytes.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                resp_body = body_bytes.decode("utf-8", errors="replace")

            # Try to pretty-print JSON
            try:
                parsed_json = json.loads(resp_body)
                resp_body = json.dumps(parsed_json, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass

    except urllib.error.HTTPError as e:
        elapsed = time.time() - start_time
        status = e.code
        reason = e.reason
        resp_headers = list(e.headers.items()) if hasattr(e, 'headers') else []
        try:
            resp_body = e.read().decode("utf-8", errors="replace")
            # Try to pretty-print JSON error body
            try:
                parsed_json = json.loads(resp_body)
                resp_body = json.dumps(parsed_json, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass
        except Exception:
            resp_body = "(could not read error body)"

    except urllib.error.URLError as e:
        elapsed = time.time() - start_time
        return f"Request failed: {e.reason}\nElapsed: {elapsed:.2f}s"

    except Exception as e:
        elapsed = time.time() - start_time
        return f"Request error: {e}\nElapsed: {elapsed:.2f}s"

    # Format output
    lines = [
        f"{method.upper()} {url}",
        f"Status: {status} {reason}",
        f"Time: {elapsed:.2f}s",
        f"Body size: {len(body_bytes)} bytes",
        "",
        "Response Headers:",
        _format_headers(resp_headers if isinstance(resp_headers, list) else list(resp_headers)),
        "",
        "Response Body:",
        _truncate(resp_body),
    ]

    return "\n".join(lines)


def _parse_headers_block(text):
    """Parse a headers block. Returns (custom_headers_dict, remaining_text)."""
    lines = text.strip().split("\n")
    custom_headers = {}
    request_line_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Check if this line looks like a request method
        if stripped.split(None, 1)[0].lower() in ("get", "post", "put", "delete", "patch", "head", "options"):
            request_line_idx = i
            break
        # Parse as header
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            custom_headers[key.strip()] = val.strip()

    if request_line_idx is None:
        return None, None, "Could not find request method line after headers."

    remaining = "\n".join(lines[request_line_idx:])
    return custom_headers, remaining, None


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    try:
        args_str = args.strip()
        if not args_str:
            return ("Usage:\n"
                    "  get <url>                    — GET request\n"
                    "  post <url>\\n<json_body>      — POST with JSON body\n"
                    "  put <url>\\n<json_body>       — PUT with JSON body\n"
                    "  delete <url>                 — DELETE request\n"
                    "  headers <headers>\\n<method> <url>  — with custom headers")

        # Split first line from body
        lines = args_str.split("\n", 1)
        first_line = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""

        first_parts = first_line.split(None, 1)
        command = first_parts[0].lower()
        cmd_rest = first_parts[1].strip() if len(first_parts) > 1 else ""

        # Command: headers
        if command == "headers":
            # Everything after "headers " is the headers block + request
            full_block = cmd_rest
            if body:
                full_block += "\n" + body
            custom_headers, remaining, err = _parse_headers_block(full_block)
            if err:
                return err

            # Now parse the remaining as a normal request
            remaining_lines = remaining.split("\n", 1)
            req_first = remaining_lines[0].strip()
            req_body = remaining_lines[1].strip() if len(remaining_lines) > 1 else ""

            req_parts = req_first.split(None, 1)
            method = req_parts[0].lower()
            url = req_parts[1] if len(req_parts) > 1 else ""

            if method not in ("get", "post", "put", "delete", "patch", "head", "options"):
                return f"Unknown HTTP method: {method}"
            if not url:
                return "No URL provided after method."

            req_data = req_body if method in ("post", "put", "patch") else None
            return _do_request(method, url, body=req_data, custom_headers=custom_headers)

        # Command: get
        elif command == "get":
            if not cmd_rest:
                return "Usage: get <url>"
            return _do_request("GET", cmd_rest)

        # Command: post
        elif command == "post":
            if not cmd_rest:
                return "Usage: post <url>\\n<json_body>"
            return _do_request("POST", cmd_rest, body=body or None)

        # Command: put
        elif command == "put":
            if not cmd_rest:
                return "Usage: put <url>\\n<json_body>"
            return _do_request("PUT", cmd_rest, body=body or None)

        # Command: delete
        elif command == "delete":
            if not cmd_rest:
                return "Usage: delete <url>"
            return _do_request("DELETE", cmd_rest)

        # Additional methods (bonus)
        elif command in ("patch", "head", "options"):
            if not cmd_rest:
                return f"Usage: {command} <url>"
            req_body = body if command == "patch" else None
            return _do_request(command.upper(), cmd_rest, body=req_body)

        else:
            return (f"Unknown command: {command}\n"
                    "Commands: get, post, put, delete, headers\n"
                    "Also supported: patch, head, options")

    except Exception as e:
        return f"API tool error: {e}"
