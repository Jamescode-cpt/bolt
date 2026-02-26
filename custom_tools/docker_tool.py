TOOL_NAME = "docker"
TOOL_DESC = """Docker container management (READ-ONLY). Queries the docker CLI for container and image info.

Commands:
  ps          — list running containers (name, image, status, ports)
  ps all      — list all containers including stopped
  images      — list images (repo, tag, size)
  logs <name> — last 50 lines of a container's logs
  stats       — container resource usage (CPU, mem, net)
  inspect <name> — detailed container info

Examples:
  docker ps
  docker ps all
  docker images
  docker logs my_container
  docker stats
  docker inspect my_container

This tool is strictly read-only. It will never stop, kill, or remove containers or images."""


import shutil
import subprocess


def _run_docker(cmd_args, timeout=15):
    """Run a docker CLI command and return stdout or an error string."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return "Error: Docker is not installed or not in PATH. Install Docker to use this tool."
    try:
        result = subprocess.run(
            [docker_bin] + cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "permission denied" in stderr.lower() or "connect:" in stderr.lower():
                return (
                    "Error: Cannot connect to Docker daemon. "
                    "Make sure Docker is running and your user is in the 'docker' group.\n"
                    f"Details: {stderr}"
                )
            return f"Error (exit {result.returncode}): {stderr or 'unknown error'}"
        return result.stdout.strip() if result.stdout.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Docker command timed out after 15 seconds."
    except Exception as e:
        return f"Error running docker: {e}"


def _format_table(header, rows, col_widths=None):
    """Format a simple aligned table from header list and row lists."""
    if not rows:
        return "(no results)"
    all_rows = [header] + rows
    if col_widths is None:
        col_widths = []
        for col_idx in range(len(header)):
            max_w = 0
            for row in all_rows:
                if col_idx < len(row):
                    max_w = max(max_w, len(str(row[col_idx])))
            col_widths.append(min(max_w, 60))
    lines = []
    for row in all_rows:
        parts = []
        for i, val in enumerate(row):
            w = col_widths[i] if i < len(col_widths) else 20
            parts.append(str(val).ljust(w))
        lines.append("  ".join(parts).rstrip())
    # Insert separator after header
    sep = "  ".join("-" * w for w in col_widths)
    lines.insert(1, sep)
    return "\n".join(lines)


# ── Blocked commands ──
_BLOCKED = {"rm", "rmi", "stop", "kill", "prune", "system"}


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    args = args.strip() if args else ""

    if not args:
        return (
            "Docker tool — read-only container management.\n"
            "Commands: ps | ps all | images | logs <name> | stats | inspect <name>\n"
            "Example: docker ps"
        )

    parts = args.split()
    cmd = parts[0].lower()

    # Safety: block any destructive subcommands
    if cmd in _BLOCKED:
        return f"Blocked: 'docker {cmd}' is a destructive operation. This tool is read-only."

    try:
        if cmd == "ps":
            show_all = len(parts) > 1 and parts[1].lower() == "all"
            fmt = "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
            docker_args = ["ps", "--format", fmt]
            if show_all:
                docker_args.insert(1, "-a")
            raw = _run_docker(docker_args)
            if raw.startswith("Error"):
                return raw
            label = "All containers:" if show_all else "Running containers:"
            return f"{label}\n{raw}"

        elif cmd == "images":
            fmt = "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"
            raw = _run_docker(["images", "--format", fmt])
            if raw.startswith("Error"):
                return raw
            return f"Docker images:\n{raw}"

        elif cmd == "logs":
            if len(parts) < 2:
                return "Usage: docker logs <container_name_or_id>"
            container = parts[1]
            # Sanitize: only allow alphanumeric, dash, underscore, dot, colon
            if not all(c.isalnum() or c in "-_.:/" for c in container):
                return "Error: Invalid container name."
            raw = _run_docker(["logs", "--tail", "50", container], timeout=10)
            if raw.startswith("Error"):
                return raw
            return f"Last 50 log lines for '{container}':\n{raw}"

        elif cmd == "stats":
            fmt = "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.PIDs}}"
            raw = _run_docker(["stats", "--no-stream", "--format", fmt], timeout=15)
            if raw.startswith("Error"):
                return raw
            return f"Container resource usage:\n{raw}"

        elif cmd == "inspect":
            if len(parts) < 2:
                return "Usage: docker inspect <container_name_or_id>"
            container = parts[1]
            if not all(c.isalnum() or c in "-_.:/" for c in container):
                return "Error: Invalid container name."
            raw = _run_docker(["inspect", container], timeout=10)
            if raw.startswith("Error"):
                return raw
            # Truncate if huge
            if len(raw) > 4000:
                raw = raw[:4000] + "\n... (truncated, output too long)"
            return f"Inspect '{container}':\n{raw}"

        else:
            return (
                f"Unknown docker command: '{cmd}'\n"
                "Available: ps | ps all | images | logs <name> | stats | inspect <name>"
            )

    except Exception as e:
        return f"Docker tool error: {e}"
