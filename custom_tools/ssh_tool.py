TOOL_NAME = "ssh"
TOOL_DESC = """SSH connection manager — save, list, test, and recall SSH host configs.

Commands:
  list                          — list all saved SSH connections
  add <name> <user@host> [port] — save a new connection
  remove <name>                 — remove a saved connection
  connect <name>                — show the SSH command (does not connect)
  test <name>                   — test connectivity (timeout 5s)
  config                        — show ~/.ssh/config contents

Examples:
  ssh list
  ssh add myserver user@192.168.1.50 22
  ssh add devbox admin@dev.example.com
  ssh connect myserver
  ssh test myserver
  ssh remove myserver
  ssh config

Connections are saved to ~/bolt/ssh_hosts.json. Passwords are NEVER stored."""


import json
import os
import subprocess


_HOSTS_FILE = os.path.expanduser("~/bolt/ssh_hosts.json")
_SAFE_BASE = os.path.realpath(os.path.expanduser("~/"))


def _load_hosts():
    """Load the saved hosts dict from disk."""
    if not os.path.exists(_HOSTS_FILE):
        return {}
    try:
        with open(_HOSTS_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, IOError):
        return {}


def _save_hosts(hosts):
    """Persist the hosts dict to disk."""
    # Validate path stays under home
    real = os.path.realpath(_HOSTS_FILE)
    if not real.startswith(_SAFE_BASE):
        return "Error: Refusing to write outside home directory."
    try:
        os.makedirs(os.path.dirname(_HOSTS_FILE), exist_ok=True)
        with open(_HOSTS_FILE, "w") as f:
            json.dump(hosts, f, indent=2)
        return None  # success
    except IOError as e:
        return f"Error saving hosts: {e}"


def _validate_name(name):
    """Only allow safe host alias names."""
    if not name or len(name) > 64:
        return False
    return all(c.isalnum() or c in "-_." for c in name)


def _format_table(header, rows):
    """Simple aligned table."""
    if not rows:
        return "(none)"
    all_rows = [header] + rows
    widths = []
    for col in range(len(header)):
        w = max(len(str(r[col])) if col < len(r) else 0 for r in all_rows)
        widths.append(min(w, 50))
    lines = []
    for row in all_rows:
        parts = [str(row[i]).ljust(widths[i]) for i in range(len(header))]
        lines.append("  ".join(parts).rstrip())
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    args = args.strip() if args else ""

    if not args:
        return (
            "SSH connection manager.\n"
            "Commands: list | add <name> <user@host> [port] | remove <name> | "
            "connect <name> | test <name> | config"
        )

    parts = args.split()
    cmd = parts[0].lower()

    try:
        # ── list ──
        if cmd == "list":
            hosts = _load_hosts()
            if not hosts:
                return "No saved SSH connections. Use 'ssh add <name> <user@host> [port]' to add one."
            rows = []
            for name, info in sorted(hosts.items()):
                user = info.get("user", "?")
                host = info.get("host", "?")
                port = str(info.get("port", 22))
                identity = info.get("identity_file", "-")
                rows.append([name, f"{user}@{host}", port, identity])
            return "Saved SSH connections:\n" + _format_table(
                ["NAME", "USER@HOST", "PORT", "KEY"], rows
            )

        # ── add ──
        elif cmd == "add":
            if len(parts) < 3:
                return "Usage: ssh add <name> <user@host> [port] [identity_file]"
            name = parts[1]
            if not _validate_name(name):
                return "Error: Invalid name. Use alphanumeric, dash, underscore, or dot (max 64 chars)."
            user_host = parts[2]
            if "@" not in user_host:
                return "Error: Must be in user@host format (e.g. admin@192.168.1.1)."
            user, host = user_host.split("@", 1)
            if not user or not host:
                return "Error: Both user and host are required (user@host)."

            port = 22
            identity_file = None
            if len(parts) >= 4:
                # Check if it looks like a port number
                if parts[3].isdigit():
                    port = int(parts[3])
                    if port < 1 or port > 65535:
                        return "Error: Port must be between 1 and 65535."
                    if len(parts) >= 5:
                        identity_file = parts[4]
                else:
                    identity_file = parts[3]

            # Validate identity file path if given
            if identity_file:
                real_id = os.path.realpath(os.path.expanduser(identity_file))
                if not real_id.startswith(_SAFE_BASE):
                    return "Error: Identity file must be under your home directory."
                identity_file = real_id

            hosts = _load_hosts()
            overwriting = name in hosts
            hosts[name] = {
                "user": user,
                "host": host,
                "port": port,
            }
            if identity_file:
                hosts[name]["identity_file"] = identity_file

            err = _save_hosts(hosts)
            if err:
                return err
            action = "Updated" if overwriting else "Saved"
            extra = f" -i {identity_file}" if identity_file else ""
            return f"{action} connection '{name}': ssh -p {port}{extra} {user}@{host}"

        # ── remove ──
        elif cmd == "remove":
            if len(parts) < 2:
                return "Usage: ssh remove <name>"
            name = parts[1]
            hosts = _load_hosts()
            if name not in hosts:
                return f"No saved connection named '{name}'. Use 'ssh list' to see all."
            del hosts[name]
            err = _save_hosts(hosts)
            if err:
                return err
            return f"Removed connection '{name}'."

        # ── connect ──
        elif cmd == "connect":
            if len(parts) < 2:
                return "Usage: ssh connect <name>"
            name = parts[1]
            hosts = _load_hosts()
            if name not in hosts:
                return f"No saved connection named '{name}'. Use 'ssh list' to see all."
            info = hosts[name]
            user = info["user"]
            host = info["host"]
            port = info.get("port", 22)
            identity = info.get("identity_file")
            cmd_parts = ["ssh"]
            if port != 22:
                cmd_parts.extend(["-p", str(port)])
            if identity:
                cmd_parts.extend(["-i", identity])
            cmd_parts.append(f"{user}@{host}")
            ssh_cmd = " ".join(cmd_parts)
            return (
                f"SSH command for '{name}':\n\n"
                f"  {ssh_cmd}\n\n"
                "Copy and paste this into your terminal to connect.\n"
                "(Interactive SSH sessions can't be run from within BOLT.)"
            )

        # ── test ──
        elif cmd == "test":
            if len(parts) < 2:
                return "Usage: ssh test <name>"
            name = parts[1]
            hosts = _load_hosts()
            if name not in hosts:
                return f"No saved connection named '{name}'. Use 'ssh list' to see all."
            info = hosts[name]
            user = info["user"]
            host = info["host"]
            port = info.get("port", 22)
            identity = info.get("identity_file")

            test_cmd = [
                "ssh",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes",
                "-p", str(port),
            ]
            if identity:
                test_cmd.extend(["-i", identity])
            test_cmd.extend([f"{user}@{host}", "echo", "BOLT_SSH_OK"])

            try:
                result = subprocess.run(
                    test_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and "BOLT_SSH_OK" in result.stdout:
                    return f"Connection test for '{name}' ({user}@{host}:{port}): SUCCESS"
                else:
                    stderr = result.stderr.strip()[:300]
                    return (
                        f"Connection test for '{name}' ({user}@{host}:{port}): FAILED\n"
                        f"Exit code: {result.returncode}\n"
                        f"Details: {stderr or 'no details'}"
                    )
            except subprocess.TimeoutExpired:
                return f"Connection test for '{name}': TIMEOUT (host unreachable or port blocked)"
            except FileNotFoundError:
                return "Error: ssh client not found. Is OpenSSH installed?"
            except Exception as e:
                return f"Error testing connection: {e}"

        # ── config ──
        elif cmd == "config":
            config_path = os.path.expanduser("~/.ssh/config")
            if not os.path.exists(config_path):
                return "No ~/.ssh/config file found."
            try:
                with open(config_path, "r") as f:
                    content = f.read()
                if not content.strip():
                    return "~/.ssh/config exists but is empty."
                # Truncate if huge
                if len(content) > 4000:
                    content = content[:4000] + "\n... (truncated)"
                return f"~/.ssh/config:\n\n{content}"
            except PermissionError:
                return "Error: Permission denied reading ~/.ssh/config."
            except IOError as e:
                return f"Error reading ~/.ssh/config: {e}"

        else:
            return (
                f"Unknown ssh command: '{cmd}'\n"
                "Available: list | add | remove | connect | test | config"
            )

    except Exception as e:
        return f"SSH tool error: {e}"
