"""BOLT custom tool — weather via wttr.in.

Uses requests to fetch from wttr.in (free community service).
Rate limited: 10s between calls. Location validated with regex.
"""

import re
import time

TOOL_NAME = "weather"
TOOL_DESC = (
    "Get weather info via wttr.in. "
    'Usage: <tool name="weather">London</tool> or '
    '<tool name="weather">Tokyo\nfull</tool> — '
    "default is one-liner, 'full' for detailed."
)

# Allow city names, coordinates, airport codes — no shell injection
LOCATION_RE = re.compile(r"^[a-zA-Z0-9 ,.'°\-+]+$")
RATE_LIMIT_SECS = 10.0
REQUEST_TIMEOUT = 15

_last_request = 0


def _rate_check():
    """Enforce global rate limit for wttr.in."""
    global _last_request
    now = time.time()
    if now - _last_request < RATE_LIMIT_SECS:
        wait = RATE_LIMIT_SECS - (now - _last_request)
        time.sleep(wait)
    _last_request = time.time()


def run(args):
    """Get weather information.

    Args: 'location' for one-liner, or 'location\\nfull' for detailed forecast.
    """
    raw = args.strip() if args else ""
    if not raw:
        return 'Usage: <tool name="weather">city name</tool> or <tool name="weather">city\nfull</tool>'

    lines = raw.split("\n", 1)
    location = lines[0].strip()
    full = len(lines) > 1 and "full" in lines[1].lower()

    if not location:
        return "No location provided."
    if len(location) > 100:
        return "Location too long (max 100 chars)."
    if not LOCATION_RE.match(location):
        return f"Invalid location: {location} — only letters, numbers, spaces, commas, periods allowed."

    try:
        import requests
    except ImportError:
        return "requests library not installed. Install with: pip install requests"

    _rate_check()

    try:
        # format=3 = one-liner, format=v2 = detailed
        if full:
            url = f"https://wttr.in/{location}?format=v2"
        else:
            url = f"https://wttr.in/{location}?format=3"

        headers = {
            "User-Agent": "BOLT/1.0 (local AI companion)",
            "Accept": "text/plain",
        }
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 404:
            return f"Location not found: {location}"
        resp.raise_for_status()

        text = resp.text.strip()
        if not text:
            return f"No weather data for {location}"

        # Cap output
        if len(text) > 3000:
            text = text[:3000] + "\n... (truncated)"

        return text

    except Exception as e:
        return f"weather error: {e}"
