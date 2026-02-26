"""BOLT custom tool — fetch URLs and extract readable text.

Uses requests + lxml.html for text extraction (NOT bs4).
Rate limited: 1 request per 2s per domain. Blocked domains list.
Truncates output to 6000 chars.
"""

import time
import re
from urllib.parse import urlparse


def _is_internal_url(url):
    """Block requests to internal/private networks."""
    import socket
    import ipaddress
    from urllib.parse import urlparse as _urlparse
    try:
        parsed = _urlparse(url)
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


TOOL_NAME = "http_fetch"
TOOL_DESC = (
    "Fetch a URL and extract readable text. "
    'Usage: <tool name="http_fetch">https://example.com</tool> — '
    "returns page text content (HTML stripped). Rate limited."
)

MAX_OUTPUT = 6000
RATE_LIMIT_SECS = 2.0
REQUEST_TIMEOUT = 15

# Domains we must never scrape (will ban IP)
BLOCKED_DOMAINS = {
    "google.com", "www.google.com",
    "bing.com", "www.bing.com",
    "yahoo.com", "www.yahoo.com",
    "search.yahoo.com",
    "google.co.uk", "google.ca",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
}

# Per-domain last-request timestamps for rate limiting
_last_request = {}


def _rate_check(domain):
    """Enforce rate limit per domain. Returns True if OK, False if too soon."""
    now = time.time()
    last = _last_request.get(domain, 0)
    if now - last < RATE_LIMIT_SECS:
        wait = RATE_LIMIT_SECS - (now - last)
        time.sleep(wait)
    _last_request[domain] = time.time()
    return True


def _extract_text_lxml(html):
    """Extract readable text from HTML using lxml."""
    from lxml import html as lxml_html
    from lxml.html.clean import Cleaner

    cleaner = Cleaner(
        scripts=True,
        javascript=True,
        style=True,
        comments=True,
        forms=False,
        page_structure=False,
    )
    doc = lxml_html.fromstring(html)
    cleaned = cleaner.clean_html(doc)
    text = cleaned.text_content()
    # Collapse whitespace
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_text_fallback(html):
    """Fallback text extraction using regex (no lxml)."""
    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def run(args):
    """Fetch a URL and return extracted text.

    Args is the URL to fetch.
    """
    url = args.strip() if args else ""
    if not url:
        return "No URL provided. Usage: <tool name=\"http_fetch\">https://example.com</tool>"

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Parse and check domain
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or ""
    except Exception:
        return f"Invalid URL: {url}"

    # Check blocked domains
    domain_lower = domain.lower()
    for blocked in BLOCKED_DOMAINS:
        if domain_lower == blocked or domain_lower.endswith("." + blocked):
            return f"Blocked domain: {domain}. This site will ban your IP if scraped. Use web_search instead."

    # Try importing requests
    try:
        import requests
    except ImportError:
        return "requests library not installed. Install with: pip install requests"

    # Rate limit
    _rate_check(domain_lower)

    # SSRF protection — block internal/private IPs
    if _is_internal_url(url):
        return "Blocked: cannot fetch from internal/private network addresses."

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; BOLT/1.0; +local)",
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")

        # If JSON, return raw
        if "json" in content_type:
            text = resp.text
        # If plain text, return raw
        elif "text/plain" in content_type:
            text = resp.text
        # HTML — extract text
        elif "html" in content_type or resp.text.strip().startswith("<"):
            try:
                text = _extract_text_lxml(resp.text)
            except Exception:
                text = _extract_text_fallback(resp.text)
        else:
            text = resp.text

        # Truncate
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + f"\n\n... (truncated, {len(resp.text)} chars total)"

        return f"Fetched {url} ({resp.status_code}):\n\n{text}" if text else f"Fetched {url} ({resp.status_code}): (empty response)"

    except Exception as e:
        return f"http_fetch error: {e}"
