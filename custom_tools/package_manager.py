"""BOLT custom tool — package query (READ-ONLY).

Cross-platform: Linux (apt/dpkg), macOS (brew).
Strictly no install/remove. Only search, info, list, check.
"""

import re
import subprocess
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import IS_MAC, get_package_manager

TOOL_NAME = "packages"
TOOL_DESC = (
    "Query installed/available packages (READ-ONLY). "
    'Usage: <tool name="packages">search python3</tool> or '
    '<tool name="packages">info curl</tool> or '
    '<tool name="packages">list python</tool> or '
    '<tool name="packages">check curl</tool>'
)

PKG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+\-:@/]*$")
MAX_OUTPUT = 5000


def _validate_pkg(name):
    if not name:
        return None, "No package name provided."
    if len(name) > 200:
        return None, "Package name too long."
    if not PKG_RE.match(name):
        return None, f"Invalid package name: {name}"
    return name, None


def _run_cmd(cmd, timeout=15):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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


# ─── apt/dpkg (Linux) ───

def _search_apt(query):
    pkg, err = _validate_pkg(query)
    if err:
        return err
    output = _run_cmd(["apt", "search", pkg], timeout=30)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return f"Search results for '{pkg}':\n{output}" if output else f"No results for '{pkg}'"


def _info_apt(name):
    pkg, err = _validate_pkg(name)
    if err:
        return err
    output = _run_cmd(["apt", "show", pkg])
    if "No packages found" in output or not output:
        output = _run_cmd(["dpkg-query", "-s", pkg])
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return output if output else f"No info found for '{pkg}'"


def _list_apt(filter_str=""):
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


def _check_apt(name):
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
    return f"{pkg}: {result}"


# ─── brew (macOS) ───

def _search_brew(query):
    pkg, err = _validate_pkg(query)
    if err:
        return err
    output = _run_cmd(["brew", "search", pkg], timeout=30)
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return f"Search results for '{pkg}':\n{output}" if output else f"No results for '{pkg}'"


def _info_brew(name):
    pkg, err = _validate_pkg(name)
    if err:
        return err
    output = _run_cmd(["brew", "info", pkg])
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return output if output else f"No info found for '{pkg}'"


def _list_brew(filter_str=""):
    output = _run_cmd(["brew", "list"])
    if filter_str:
        pkg, err = _validate_pkg(filter_str)
        if err:
            return err
        lines = [l for l in output.splitlines() if filter_str.lower() in l.lower()]
        output = "\n".join(lines) if lines else f"No installed packages matching '{filter_str}'"
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n... (truncated)"
    return output if output else "No installed packages found"


def _check_brew(name):
    pkg, err = _validate_pkg(name)
    if err:
        return err
    try:
        result = subprocess.run(
            ["brew", "list", pkg], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            # Get version
            ver_out = _run_cmd(["brew", "info", "--json=v1", pkg])
            return f"{pkg}: installed (via Homebrew)"
        return f"{pkg}: NOT installed"
    except Exception:
        return f"{pkg}: unable to check"


def run(args):
    """Query packages (READ-ONLY)."""
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

    if cmd in ("install", "remove", "purge", "autoremove", "upgrade", "update", "uninstall"):
        return f"Refused: '{cmd}' is not allowed. This tool is READ-ONLY."

    pkg_mgr = get_package_manager()
    if not pkg_mgr:
        return "No package manager found. Install apt (Linux) or brew (macOS)."

    try:
        if IS_MAC:
            if cmd == "search":
                return _search_brew(arg)
            elif cmd in ("info", "show"):
                return _info_brew(arg)
            elif cmd == "list":
                return _list_brew(arg)
            elif cmd == "check":
                return _check_brew(arg)
        else:
            if cmd == "search":
                return _search_apt(arg)
            elif cmd in ("info", "show"):
                return _info_apt(arg)
            elif cmd == "list":
                return _list_apt(arg)
            elif cmd == "check":
                return _check_apt(arg)

        return f"Unknown subcommand: {cmd}\nAvailable: search, info, list, check"
    except Exception as e:
        return f"packages error: {e}"
