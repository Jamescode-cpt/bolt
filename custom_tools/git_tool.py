"""BOLT custom tool — git operations.

Wraps git via subprocess. Path restricted to /home/mobilenode/.
Blocks dangerous commands (push --force, reset --hard, clean).
"""

import subprocess
import os
import shlex

TOOL_NAME = "git"
TOOL_DESC = (
    "Run git commands safely. "
    'Usage: <tool name="git">status</tool> or '
    '<tool name="git">log --oneline -10</tool> — '
    "supports: status, log, diff, add, commit, branch, checkout, stash, remote, show, tag"
)

ALLOWED_ROOT = "/home/mobilenode"
GIT_TIMEOUT = 30

# Allowed base git subcommands
ALLOWED_CMDS = {
    "status", "log", "diff", "add", "commit", "branch", "checkout",
    "stash", "remote", "show", "tag", "init", "fetch", "pull", "push",
    "merge", "rebase", "cherry-pick", "blame", "shortlog", "rev-parse",
    "config", "ls-files", "ls-tree", "reflog",
}

# Blocked flag patterns (dangerous operations)
BLOCKED_PATTERNS = [
    "push --force",
    "push -f",
    "reset --hard",
    "clean -f",
    "clean -fd",
    "clean -fx",
    "clean --force",
]


def _find_git_dir(start_dir):
    """Walk up from start_dir to find a git repo root."""
    current = os.path.realpath(start_dir)
    while current.startswith(ALLOWED_ROOT):
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def run(args):
    """Run a git command.

    Args is the git subcommand + arguments, e.g. 'status' or 'log --oneline -10'.
    Optional: last line can be a path to run git in (must be under /home/mobilenode/).
    """
    raw = args.strip() if args else ""
    if not raw:
        return "No git command provided. Usage: <tool name=\"git\">status</tool>"

    lines = raw.split("\n")
    cmd_line = lines[0].strip()

    # Check if last line is a directory path
    work_dir = None
    if len(lines) > 1:
        potential_dir = lines[-1].strip()
        if os.path.isdir(potential_dir):
            work_dir = potential_dir
            # If there's a middle line, it's part of the command (e.g., commit message)
            if len(lines) > 2:
                cmd_line = "\n".join(l.strip() for l in lines[:-1])

    # Strip leading 'git' if user included it
    if cmd_line.startswith("git "):
        cmd_line = cmd_line[4:]

    # Parse subcommand
    parts = cmd_line.split(None, 1)
    subcmd = parts[0].lower() if parts else ""

    if subcmd not in ALLOWED_CMDS:
        return f"Git subcommand not allowed: {subcmd}\nAllowed: {', '.join(sorted(ALLOWED_CMDS))}"

    # Check for blocked dangerous patterns
    full_cmd_lower = cmd_line.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in full_cmd_lower:
            return f"Blocked for safety: 'git {cmd_line}'. This is a destructive operation — use shell tool if you really need it."

    # Determine working directory
    if work_dir:
        work_dir = os.path.realpath(os.path.expanduser(work_dir))
    else:
        # Try to find a git repo from common locations
        for candidate in ["/home/mobilenode/bolt", "/home/mobilenode"]:
            git_root = _find_git_dir(candidate)
            if git_root:
                work_dir = git_root
                break
        if not work_dir:
            work_dir = ALLOWED_ROOT

    # Safety: restrict to home
    if not work_dir.startswith(ALLOWED_ROOT):
        return f"Access denied: git restricted to {ALLOWED_ROOT}/"

    try:
        cmd_parts = ["git"] + shlex.split(cmd_line)
        result = subprocess.run(
            cmd_parts, shell=False, capture_output=True, text=True,
            timeout=GIT_TIMEOUT, cwd=work_dir,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            # Git often sends normal info to stderr
            output += ("\n" if output else "") + result.stderr
        if not output.strip():
            output = f"(exit code {result.returncode})"

        # Truncate
        if len(output) > 8000:
            output = output[:8000] + "\n... (truncated)"

        return output.strip()

    except subprocess.TimeoutExpired:
        return f"Git command timed out after {GIT_TIMEOUT}s"
    except Exception as e:
        return f"git error: {e}"
