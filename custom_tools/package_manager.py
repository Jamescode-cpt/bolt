"""BOLT custom tool — apt/dpkg package query (READ-ONLY).

Strictly no install/remove. Only search, info, list, check.
Package names validated with regex.
"""

import re
import subprocess

TOOL_NAME = "packages"
TOOL_DESC = (
    "Query installed/available packages (READ-ONLY). "
    'Usage: <tool name="packages">search python3</tool> or '
    '<tool name="packages">info curl</tool> or '
    '<tool name="packages">list python</tool> or '
    '<tool name="packages">check curl</tool>'
)

# Package name: alphanumeric, hyphens, dots, plus, colon (for arch qualifiers)
PKG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+\-:]*$")
MAX_OUTPUT = 5000


def _validate_pkg(name):
    """Validate package name."""
    if not name:
        return None, "No package name provided."
    if len(name) > 200:
        return None, "Package name too long."
    if not PKG_RE.match(name):
        return None, f"Invalid package name: {name}"
    return name, None


def _run_cmd(cmd, timeout=15):
    """Run a command and return output."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        return output.strip()
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}"
    except Exception as e:
        return f"Error: {e}"


def _search(query):
    """Search available packages."""
    pkg, err = _validate_pkg(query)
    if err:
        return err
    output = _run_cmd(["apt", "search", pkg], timeout=30)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return f"Search results for '{pkg}':\n{output}" if output else f"No results for '{pkg}'"


def _info(name):
    """Show package info."""
    pkg, err = _validate_pkg(name)
    if err:
        return err
    # Try apt show first (more detail), fall back to dpkg
    output = _run_cmd(["apt", "show", pkg])
    if "No packages found" in output or not output:
        output = _run_cmd(["dpkg-query", "-s", pkg])
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return output if output else f"No info found for '{pkg}'"


def _list_installed(filter_str=""):
    """List installed packages, optionally filtered."""
    if filter_str:
        pkg, err = _validate_pkg(filter_str)
        if err:
            return err
        output = _run_cmd(["dpkg-query", "-l", f"*{pkg}*"])
    else:
        output = _run_cmd(["dpkg-query", "-l"])
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return output if output else "No installed packages found"


def _check(name):
    """Check if a package is installed."""
    pkg, err = _validate_pkg(name)
    if err:
        return err
    result = _run_cmd(["dpkg-query", "-W", "-f=${Status}\n${Version}\n", pkg])
    if "not-installed" in result or "no packages found" in result.lower():
        return f"{pkg}: NOT installed"
    elif "install ok installed" in result:
        lines = result.strip().split("\n")
        version = lines[1] if len(lines) > 1 else "unknown"
        return f"{pkg}: installed (version {version})"
    else:
        return f"{pkg}: {result}"


def run(args):
    """Query packages (READ-ONLY).

    Args: 'search <query>', 'info <package>', 'list [filter]', 'check <package>'.
    """
    raw = args.strip() if args else ""
    if not raw:
        return (
            'Usage:\n'
            '  <tool name="packages">search python3</tool>\n'
            '  <tool name="packages">info curl</tool>\n'
            '  <tool name="packages">list python</tool>\n'
            '  <tool name="packages">check curl</tool>'
        )

    parts = raw.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    # Block any install/remove/purge attempts
    if cmd in ("install", "remove", "purge", "autoremove", "upgrade", "update"):
        return f"Refused: '{cmd}' is not allowed. This tool is READ-ONLY."

    try:
        if cmd == "search":
            return _search(arg)
        elif cmd == "info" or cmd == "show":
            return _info(arg)
        elif cmd == "list":
            return _list_installed(arg)
        elif cmd == "check":
            return _check(arg)
        else:
            return (
                f"Unknown subcommand: {cmd}\n"
                "Available: search, info, list, check"
            )
    except Exception as e:
        return f"packages error: {e}"
