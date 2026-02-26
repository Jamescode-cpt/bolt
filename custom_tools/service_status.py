"""BOLT custom tool: read-only systemd service status queries."""

import subprocess

TOOL_NAME = "services"
TOOL_DESC = (
    "Systemd service info (READ-ONLY, never starts/stops/restarts).\n"
    "  list              - list running services\n"
    "  status <name>     - show status of a specific service\n"
    "  check <name>      - quick active/inactive/failed check"
)

# Hard block on anything that could mutate service state.
_FORBIDDEN_ACTIONS = {"start", "stop", "restart", "enable", "disable", "mask", "unmask", "reload", "kill"}


def _sanitize_name(name):
    """Basic validation of a service name to avoid injection."""
    name = name.strip()
    # Allow alphanumerics, dash, underscore, dot, @ (for template instances)
    if not name:
        raise ValueError("Service name cannot be empty.")
    for ch in name:
        if not (ch.isalnum() or ch in "-_.@"):
            raise ValueError(f"Invalid character in service name: '{ch}'")
    # Ensure it doesn't look like a flag
    if name.startswith("-"):
        raise ValueError("Service name cannot start with a dash.")
    return name


def _run_systemctl(subcmd_args, timeout=10):
    """Run a systemctl command and return stdout or an error string."""
    cmd = ["systemctl"] + subcmd_args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout.strip()
        err = result.stderr.strip()
        # systemctl status returns non-zero for inactive/failed services,
        # but still produces useful output.
        if output:
            return output
        if err:
            return f"(exit {result.returncode}) {err}"
        return f"(exit {result.returncode}, no output)"
    except FileNotFoundError:
        return "Error: systemctl not found. Is systemd available on this system?"
    except subprocess.TimeoutExpired:
        return "Error: systemctl command timed out."


def _list_running():
    """List running systemd services."""
    return _run_systemctl([
        "list-units",
        "--type=service",
        "--state=running",
        "--no-pager",
        "--no-legend",
    ])


def _status(name):
    """Show full status of a named service."""
    try:
        safe_name = _sanitize_name(name)
    except ValueError as e:
        return f"Error: {e}"
    return _run_systemctl(["status", safe_name, "--no-pager"], timeout=10)


def _check(name):
    """Quick is-active check for a service."""
    try:
        safe_name = _sanitize_name(name)
    except ValueError as e:
        return f"Error: {e}"
    try:
        result = subprocess.run(
            ["systemctl", "is-active", safe_name],
            capture_output=True, text=True, timeout=5
        )
        state = result.stdout.strip() or "unknown"
        return f"{safe_name}: {state}"
    except FileNotFoundError:
        return "Error: systemctl not found."
    except subprocess.TimeoutExpired:
        return "Error: systemctl command timed out."


def run(args):
    """Entry point called by BOLT tool loop."""
    args = (args or "").strip()
    if not args:
        return "Usage:\n" + TOOL_DESC

    parts = args.split(None, 1)
    command = parts[0].lower()

    # Safety: block any mutating verb even if someone tries to sneak it in
    if command in _FORBIDDEN_ACTIONS:
        return f"DENIED: '{command}' is a mutating action. This tool is read-only."

    if command == "list":
        return _list_running()

    if command == "status":
        if len(parts) < 2:
            return "Error: provide a service name.  Usage: status <name>"
        return _status(parts[1])

    if command == "check":
        if len(parts) < 2:
            return "Error: provide a service name.  Usage: check <name>"
        return _check(parts[1])

    return f"Unknown subcommand: '{command}'\n\n{TOOL_DESC}"
