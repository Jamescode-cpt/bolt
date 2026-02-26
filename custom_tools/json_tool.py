"""BOLT custom tool — JSON pretty-print, validate, and jq query.

Input auto-detected as JSON string or file path.
Path-restricted to ~/. Uses stdlib json + subprocess jq.
"""

import json
import os
import subprocess

TOOL_NAME = "json_tool"
TOOL_DESC = (
    "Pretty-print, validate, or query JSON. "
    'Usage: <tool name="json_tool">pretty\n{"key":"val"}</tool> or '
    '<tool name="json_tool">query .key\n/path/to/file.json</tool> or '
    '<tool name="json_tool">validate\n{"bad json</tool>'
)

HOME = os.path.expanduser("~")
MAX_INPUT = 500 * 1024  # 500KB
MAX_OUTPUT = 5000


def _validate_path(path):
    """Validate path is under home directory."""
    expanded = os.path.realpath(os.path.expanduser(path))
    if not expanded.startswith(HOME):
        return None, f"Blocked: {path} is outside ~/. Only files under {HOME}/ allowed."
    return expanded, None


def _load_json(source):
    """Load JSON from a string or file path. Returns (data, raw_str, error)."""
    source = source.strip()

    # Try as file path first if it looks like one
    if (source.startswith("/") or source.startswith("~") or
            source.startswith("./")) and "\n" not in source:
        path, err = _validate_path(source)
        if err:
            return None, None, err
        if os.path.isfile(path):
            size = os.path.getsize(path)
            if size > MAX_INPUT:
                return None, None, f"File too large ({size} bytes, max {MAX_INPUT})"
            try:
                with open(path, "r") as f:
                    raw = f.read()
                data = json.loads(raw)
                return data, raw, None
            except json.JSONDecodeError as e:
                return None, raw, f"Invalid JSON in {source}: {e}"
            except Exception as e:
                return None, None, f"Error reading {source}: {e}"

    # Try as raw JSON string
    if len(source) > MAX_INPUT:
        return None, None, f"Input too large ({len(source)} bytes, max {MAX_INPUT})"
    try:
        data = json.loads(source)
        return data, source, None
    except json.JSONDecodeError as e:
        return None, source, f"Invalid JSON: {e}"


def _pretty(source):
    """Pretty-print JSON."""
    data, raw, err = _load_json(source)
    if err:
        return err
    output = json.dumps(data, indent=2, ensure_ascii=False)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return output


def _validate(source):
    """Validate JSON and report errors."""
    data, raw, err = _load_json(source)
    if err:
        return f"INVALID: {err}"
    # Count keys/items
    if isinstance(data, dict):
        return f"VALID JSON object with {len(data)} keys"
    elif isinstance(data, list):
        return f"VALID JSON array with {len(data)} items"
    else:
        return f"VALID JSON: {type(data).__name__}"


def _query(expression, source):
    """Query JSON with jq."""
    if not expression:
        return "No jq expression provided."

    # Load the JSON source
    data, raw, err = _load_json(source)
    if data is None and raw is None:
        return err if err else "Could not load JSON input."

    # Use the raw string for jq (even if invalid for json.loads, jq may handle it)
    json_input = raw if raw else source

    try:
        result = subprocess.run(
            ["jq", expression],
            input=json_input,
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            err_msg = result.stderr.strip() if result.stderr else "jq error"
            return f"jq error: {err_msg}"
        if not output:
            return "jq returned empty result (null?)"
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n... (truncated)"
        return output
    except FileNotFoundError:
        return "jq not found. Install with: sudo apt install jq"
    except subprocess.TimeoutExpired:
        return "jq query timed out"
    except Exception as e:
        return f"jq error: {e}"


def run(args):
    """Pretty-print, validate, or query JSON.

    Args formats:
      - 'pretty\\n<json or filepath>'
      - 'validate\\n<json or filepath>'
      - 'query <jq-expr>\\n<json or filepath>'
    """
    raw = args.strip() if args else ""
    if not raw:
        return (
            'Usage:\n'
            '  <tool name="json_tool">pretty\n{"key":"value"}</tool>\n'
            '  <tool name="json_tool">validate\n{"bad json</tool>\n'
            '  <tool name="json_tool">query .key\n{"key":"val"}</tool>'
        )

    lines = raw.split("\n", 1)
    cmd_line = lines[0].strip()
    source = lines[1].strip() if len(lines) > 1 else ""

    cmd_parts = cmd_line.split(None, 1)
    cmd = cmd_parts[0].lower()

    try:
        if cmd == "pretty" or cmd == "format":
            if not source:
                # Maybe the whole input is JSON
                return _pretty(cmd_line)
            return _pretty(source)
        elif cmd == "validate" or cmd == "check":
            if not source:
                return _validate(cmd_line)
            return _validate(source)
        elif cmd == "query" or cmd == "jq":
            expr = cmd_parts[1] if len(cmd_parts) > 1 else ""
            if not expr:
                return "No jq expression provided. Usage: query .key\\n<json>"
            if not source:
                return "No JSON input provided after the jq expression."
            return _query(expr, source)
        else:
            # Try to auto-detect: if it looks like JSON, pretty-print it
            return _pretty(raw)
    except Exception as e:
        return f"json_tool error: {e}"
