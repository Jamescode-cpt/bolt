"""BOLT custom tool — RSS/Atom feed reader.

Pure stdlib — uses xml.etree.ElementTree for parsing, urllib for fetching.
Persists subscriptions to ~/bolt/rss_feeds.json.
Supports both RSS 2.0 and Atom feed formats.
"""

import json
import os


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


TOOL_NAME = "rss"
TOOL_DESC = (
    "RSS/Atom feed reader. "
    'Usage: <tool name="rss">add https://example.com/feed.xml MyFeed</tool> — subscribe | '
    '<tool name="rss">list</tool> — list feeds | '
    '<tool name="rss">read</tool> — latest entries from all feeds | '
    '<tool name="rss">read MyFeed</tool> — entries from specific feed | '
    '<tool name="rss">remove MyFeed</tool> — unsubscribe'
)

HOME = "/home/mobilenode"
FEEDS_FILE = os.path.join(HOME, "bolt", "rss_feeds.json")

# Atom namespace
ATOM_NS = "http://www.w3.org/2005/Atom"


def _validate_path(path):
    """Ensure path stays under HOME."""
    real = os.path.realpath(path)
    if not real.startswith(HOME):
        raise ValueError(f"Path escapes home directory: {real}")
    return real


def _load_feeds():
    """Load subscribed feeds from disk. Returns dict {name: url}."""
    try:
        _validate_path(FEEDS_FILE)
        if os.path.exists(FEEDS_FILE):
            with open(FEEDS_FILE, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_feeds(feeds):
    """Persist feeds to disk."""
    _validate_path(FEEDS_FILE)
    os.makedirs(os.path.dirname(FEEDS_FILE), exist_ok=True)
    with open(FEEDS_FILE, "w") as f:
        json.dump(feeds, f, indent=2)


def _fetch_url(url, timeout=30):
    """Fetch URL content. Returns (bytes, error_string)."""
    import urllib.request
    import urllib.error

    # SSRF protection — block internal/private IPs
    if _is_internal_url(url):
        return None, "Blocked: cannot fetch from internal/private network addresses."

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "BOLT-RSS-Reader/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        })
        response = urllib.request.urlopen(req, timeout=timeout)
        data = response.read()
        response.close()
        return data, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"URL error: {e.reason}"
    except Exception as e:
        return None, f"Fetch error: {e}"


def _truncate(text, max_len=200):
    """Truncate text to max_len, adding ellipsis if needed."""
    if not text:
        return ""
    text = text.strip()
    # Strip HTML tags (basic)
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _parse_feed(xml_data):
    """Parse RSS 2.0 or Atom feed. Returns (feed_title, [entries])."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        return None, f"XML parse error: {e}"

    entries = []
    feed_title = ""

    # Detect format
    tag = root.tag.lower()
    # Strip namespace if present
    if "}" in tag:
        tag = tag.split("}", 1)[1]

    if tag == "rss":
        # RSS 2.0 format
        channel = root.find("channel")
        if channel is None:
            return "Unknown", []

        title_el = channel.find("title")
        feed_title = title_el.text if title_el is not None and title_el.text else "Untitled"

        for item in channel.findall("item")[:10]:
            entry = {}
            t = item.find("title")
            entry["title"] = t.text if t is not None and t.text else "(no title)"
            l = item.find("link")
            entry["link"] = l.text if l is not None and l.text else ""
            d = item.find("description")
            entry["description"] = _truncate(d.text) if d is not None and d.text else ""
            p = item.find("pubDate")
            entry["date"] = p.text if p is not None and p.text else ""
            entries.append(entry)

    elif tag == "feed":
        # Atom format — need to handle namespace
        ns = {"atom": ATOM_NS}

        # Try with namespace first, then without
        title_el = root.find("atom:title", ns)
        if title_el is None:
            title_el = root.find("title")
        feed_title = title_el.text if title_el is not None and title_el.text else "Untitled"

        # Find entries
        items = root.findall("atom:entry", ns)
        if not items:
            items = root.findall("entry")

        for item in items[:10]:
            entry = {}

            t = item.find("atom:title", ns)
            if t is None:
                t = item.find("title")
            entry["title"] = t.text if t is not None and t.text else "(no title)"

            # Atom links are in <link href="..."/>
            l = item.find("atom:link", ns)
            if l is None:
                l = item.find("link")
            if l is not None:
                entry["link"] = l.get("href", l.text or "")
            else:
                entry["link"] = ""

            # Summary or content
            s = item.find("atom:summary", ns)
            if s is None:
                s = item.find("summary")
            if s is None:
                s = item.find("atom:content", ns)
            if s is None:
                s = item.find("content")
            entry["description"] = _truncate(s.text) if s is not None and s.text else ""

            # Date: updated or published
            d = item.find("atom:updated", ns)
            if d is None:
                d = item.find("updated")
            if d is None:
                d = item.find("atom:published", ns)
            if d is None:
                d = item.find("published")
            entry["date"] = d.text if d is not None and d.text else ""

            entries.append(entry)
    else:
        # Try a generic approach — look for item or entry elements
        return None, f"Unrecognized feed format (root tag: {root.tag})"

    return feed_title, entries


def _format_entries(feed_name, entries):
    """Format entries for display."""
    if not entries:
        return f"  {feed_name}: no entries found"

    lines = [f"--- {feed_name} ({len(entries)} entries) ---"]
    for i, entry in enumerate(entries, 1):
        lines.append(f"\n  [{i}] {entry.get('title', '(no title)')}")
        if entry.get("date"):
            lines.append(f"      Date: {entry['date']}")
        if entry.get("link"):
            lines.append(f"      Link: {entry['link']}")
        if entry.get("description"):
            lines.append(f"      {entry['description']}")

    return "\n".join(lines)


def _cmd_add(rest):
    """Subscribe to a feed."""
    parts = rest.split(None, 1)
    if not parts:
        return "Usage: add <url> [name]\nExample: add https://example.com/feed.xml MyFeed"

    url = parts[0]
    if not url.startswith(("http://", "https://")):
        return f"Invalid URL: {url} — must start with http:// or https://"

    # Generate name from URL if not provided
    if len(parts) > 1:
        name = parts[1].strip()
    else:
        # Extract a name from the URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        name = parsed.hostname or "feed"
        name = name.replace("www.", "").split(".")[0]

    feeds = _load_feeds()

    # Check if already subscribed
    if name in feeds:
        if feeds[name] == url:
            return f"Already subscribed to '{name}' ({url})"
        return f"Name '{name}' already used for {feeds[name]}. Use a different name."

    # Verify the feed is reachable and parseable
    data, err = _fetch_url(url)
    if err:
        return f"Could not fetch feed: {err}\nURL: {url}"

    result = _parse_feed(data)
    if isinstance(result, tuple) and isinstance(result[1], str) and result[0] is None:
        return f"Could not parse feed: {result[1]}\nURL: {url}"

    feed_title, entries = result
    feeds[name] = url

    try:
        _save_feeds(feeds)
    except Exception as e:
        return f"Failed to save subscription: {e}"

    entry_count = len(entries) if isinstance(entries, list) else 0
    return (
        f"Subscribed to '{name}'\n"
        f"  URL: {url}\n"
        f"  Feed title: {feed_title}\n"
        f"  Entries found: {entry_count}"
    )


def _cmd_list():
    """List all subscribed feeds."""
    feeds = _load_feeds()
    if not feeds:
        return "No feed subscriptions. Use 'add <url> [name]' to subscribe."

    lines = [f"Subscribed feeds ({len(feeds)}):"]
    for name, url in sorted(feeds.items()):
        lines.append(f"  {name}: {url}")
    return "\n".join(lines)


def _cmd_read(rest):
    """Fetch and display entries from feed(s)."""
    feeds = _load_feeds()
    if not feeds:
        return "No feed subscriptions. Use 'add <url> [name]' to subscribe."

    # Determine which feeds to read
    if rest:
        query = rest.strip()
        # Match by name or URL
        matched = {}
        for name, url in feeds.items():
            if query.lower() == name.lower() or query == url:
                matched[name] = url
        if not matched:
            # Partial match
            for name, url in feeds.items():
                if query.lower() in name.lower() or query in url:
                    matched[name] = url
        if not matched:
            return f"No feed matching '{query}'. Use 'list' to see subscriptions."
        target_feeds = matched
    else:
        target_feeds = feeds

    results = []
    for name, url in target_feeds.items():
        data, err = _fetch_url(url)
        if err:
            results.append(f"--- {name}: fetch error: {err} ---")
            continue

        parsed = _parse_feed(data)
        if isinstance(parsed, tuple) and isinstance(parsed[1], str) and parsed[0] is None:
            results.append(f"--- {name}: parse error: {parsed[1]} ---")
            continue

        feed_title, entries = parsed
        display_name = f"{name} ({feed_title})" if feed_title and feed_title != name else name
        results.append(_format_entries(display_name, entries))

    return "\n\n".join(results)


def _cmd_remove(rest):
    """Unsubscribe from a feed."""
    if not rest:
        return "Usage: remove <name_or_url>\nExample: remove MyFeed"

    feeds = _load_feeds()
    if not feeds:
        return "No feed subscriptions to remove."

    query = rest.strip()

    # Find by exact name first
    if query in feeds:
        url = feeds.pop(query)
        _save_feeds(feeds)
        return f"Unsubscribed from '{query}' ({url})"

    # Find by URL
    for name, url in list(feeds.items()):
        if query == url:
            feeds.pop(name)
            _save_feeds(feeds)
            return f"Unsubscribed from '{name}' ({url})"

    # Case-insensitive name match
    for name in list(feeds.keys()):
        if query.lower() == name.lower():
            url = feeds.pop(name)
            _save_feeds(feeds)
            return f"Unsubscribed from '{name}' ({url})"

    return f"No feed matching '{query}'. Use 'list' to see subscriptions."


def run(args):
    """RSS/Atom feed reader.

    Args: 'add <url> [name]' | 'list' | 'read [name]' | 'remove <name>'
    """
    raw = args.strip() if args else ""

    if not raw:
        return (
            "RSS feed reader. Commands:\n"
            "  add <url> [name]      — subscribe to a feed\n"
            "  list                  — list subscribed feeds\n"
            "  read [name_or_url]    — show latest entries\n"
            "  remove <name_or_url>  — unsubscribe"
        )

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    try:
        if cmd == "add":
            return _cmd_add(rest)
        elif cmd == "list" or cmd == "ls":
            return _cmd_list()
        elif cmd == "read" or cmd == "fetch" or cmd == "show":
            return _cmd_read(rest)
        elif cmd == "remove" or cmd == "rm" or cmd == "delete" or cmd == "unsub":
            return _cmd_remove(rest)
        else:
            return (
                f"Unknown command: {cmd}\n"
                "Valid commands: add, list, read, remove"
            )
    except Exception as e:
        return f"rss error: {e}"
