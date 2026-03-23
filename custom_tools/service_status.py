"""BOLT custom tool: read-only service status queries.

Cross-platform: Linux (systemctl), macOS (launchctl).
"""

import subprocess
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from platform_utils import IS_MAC, IS_LINUX

TOOL_NAME = "services"
TOOL_DESC = (
    "Service info (READ-ONLY, never starts/stops/restarts).\n"
    "  list              - list running services\n"
    "  status <name>     - show status of a specific service\n"
    "  check <name>      - quick active/inactive/failed check"
)

_FORBIDDEN_ACTIONS = {"start", "stop", "restart", "enable", "disable", "mask", "unmask", "reload", "kill"}


def _sanitize_name(name):
    name = name.strip()
    if not name:
        raise ValueError("Service name cannot be empty.")
    for ch in name:
        if not (ch.isalnum() or ch in "-_.@"):
            raise ValueError(f"Invalid character in service name: '{ch}'")
    if name.startswith("-"):
        raise ValueError("Service name cannot start with a dash.")
    return name


def _run_cmd(cmd, timeout=10):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        err = result.stderr.strip()
        if output:
            return output
        if err:
            return f"(exit {result.returncode}) {err}"
        return f"(exit {result.returncode}, no output)"
    except FileNotFoundError:
        return f"Error: {cmd[0]} not found."
    except subprocess.TimeoutExpired:
        return "Error: command timed out."


# ─── Linux (systemd) ───

def _list_running_systemd():
    return _run_cmd(["systemctl", "list-units", "--type=service", "--state=running", "--no-pager", "--no-legend"])


def _status_systemd(name):
    try:
        safe_name = _sanitize_name(name)
    except ValueError as e:
        return f"Error: {e}"
    return _run_cmd(["systemctl", "status", safe_name, "--no-pager"])


def _check_systemd(name):
    try:
        safe_name = _sanitize_name(name)
    except ValueError as e:
        return f"Error: {e}"
    try:
        result = subprocess.run(
            ["systemctl", "is-active", safe_name],
            capture_output=True, text=True, timeout=5,
        )
        state = result.stdout.strip() or "unknown"
        return f"{safe_name}: {state}"
    except FileNotFoundError:
        return "Error: systemctl not found."
    except subprocess.TimeoutExpired:
        return "Error: command timed out."


# ─── macOS (launchd) ───

def _list_running_launchd():
    return _run_cmd(["launchctl", "list"])


def _status_launchd(name):
    try:
        safe_name = _sanitize_name(name)
    except ValueError as e:
        return f"Error: {e}"
    # Try to find the service in launchctl list
    output = _run_cmd(["launchctl", "list"])
    lines = ["Service info for: " + safe_name, ""]
    found = False
    for line in output.splitlines():
        if safe_name.lower() in line.lower():
            lines.append(line)
            found = True
    if not found:
        lines.append(f"No service matching '{safe_name}' found in launchctl list.")
        lines.append("Note: on macOS, service names are like 'com.apple.Finder' or 'homebrew.mxcl.ollama'")
    return "\n".join(lines)


def _check_launchd(name):
    try:
        safe_name = _sanitize_name(name)
    except ValueError as e:
        return f"Error: {e}"
    try:
        result = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if safe_name.lower() in line.lower():
                parts = line.split()
                pid = parts[0] if parts else "-"
                status = "running" if pid != "-" else "not running"
                return f"{safe_name}: {status} (PID: {pid})"
        return f"{safe_name}: not found in launchctl"
    except Exception as e:
        return f"Error: {e}"


def run(args):
    """Entry point called by BOLT tool loop."""
    args = (args or "").strip()
    if not args:
        return "Usage:\n" + TOOL_DESC

    parts = args.split(None, 1)
    command = parts[0].lower()

    if command in _FORBIDDEN_ACTIONS:
        return f"DENIED: '{command}' is a mutating action. This tool is read-only."

    if command == "list":
        return _list_running_launchd() if IS_MAC else _list_running_systemd()

    if command == "status":
        if len(parts) < 2:
            return "Error: provide a service name.  Usage: status <name>"
        return _status_launchd(parts[1]) if IS_MAC else _status_systemd(parts[1])

    if command == "check":
        if len(parts) < 2:
            return "Error: provide a service name.  Usage: check <name>"
        return _check_launchd(parts[1]) if IS_MAC else _check_systemd(parts[1])

    return f"Unknown subcommand: '{command}'\n\n{TOOL_DESC}"
