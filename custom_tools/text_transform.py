"""BOLT custom tool: text encoding, decoding, and transformation utilities."""

import base64
import hashlib
import urllib.parse

TOOL_NAME = "transform"
TOOL_DESC = (
    "Text transformations (stdlib only).\n"
    "  base64_encode <text>  - encode to base64\n"
    "  base64_decode <text>  - decode from base64\n"
    "  url_encode <text>     - URL-encode\n"
    "  url_decode <text>     - URL-decode\n"
    "  upper <text>          - UPPERCASE\n"
    "  lower <text>          - lowercase\n"
    "  reverse <text>        - reverse string\n"
    "  count <text>          - char / word / line counts\n"
    "  md5 <text>            - MD5 hex digest\n"
    "  sha256 <text>         - SHA-256 hex digest"
)


def _require_text(parts, cmd_name):
    """Pull the text portion from split args, or return an error string."""
    if len(parts) < 2:
        return None, f"Error: provide text.  Usage: {cmd_name} <text>"
    return parts[1], None


def run(args):
    """Entry point called by BOLT tool loop."""
    args = (args or "").strip()
    if not args:
        return "Usage:\n" + TOOL_DESC

    parts = args.split(None, 1)
    command = parts[0].lower()

    # --- base64 encode ---
    if command == "base64_encode":
        text, err = _require_text(parts, "base64_encode")
        if err:
            return err
        try:
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            return encoded
        except Exception as e:
            return f"Error encoding base64: {e}"

    # --- base64 decode ---
    if command == "base64_decode":
        text, err = _require_text(parts, "base64_decode")
        if err:
            return err
        try:
            decoded = base64.b64decode(text.encode("ascii")).decode("utf-8", errors="replace")
            return decoded
        except Exception as e:
            return f"Error decoding base64: {e}"

    # --- url encode ---
    if command == "url_encode":
        text, err = _require_text(parts, "url_encode")
        if err:
            return err
        return urllib.parse.quote(text, safe="")

    # --- url decode ---
    if command == "url_decode":
        text, err = _require_text(parts, "url_decode")
        if err:
            return err
        try:
            return urllib.parse.unquote(text)
        except Exception as e:
            return f"Error decoding URL: {e}"

    # --- upper ---
    if command == "upper":
        text, err = _require_text(parts, "upper")
        if err:
            return err
        return text.upper()

    # --- lower ---
    if command == "lower":
        text, err = _require_text(parts, "lower")
        if err:
            return err
        return text.lower()

    # --- reverse ---
    if command == "reverse":
        text, err = _require_text(parts, "reverse")
        if err:
            return err
        return text[::-1]

    # --- count ---
    if command == "count":
        text, err = _require_text(parts, "count")
        if err:
            return err
        chars = len(text)
        words = len(text.split())
        lines = text.count("\n") + (1 if text else 0)
        return f"Characters: {chars}\nWords:      {words}\nLines:      {lines}"

    # --- md5 ---
    if command == "md5":
        text, err = _require_text(parts, "md5")
        if err:
            return err
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    # --- sha256 ---
    if command == "sha256":
        text, err = _require_text(parts, "sha256")
        if err:
            return err
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    return f"Unknown subcommand: '{command}'\n\n{TOOL_DESC}"
