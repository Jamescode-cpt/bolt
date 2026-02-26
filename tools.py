"""BOLT built-in tool system — shell, files, code execution."""

import subprocess
import os
import re
import sys
import importlib.util
from config import TOOL_TIMEOUT

# ─── Security: path and command restrictions ───

_HOME_DIR = os.path.expanduser("~")
_BOLT_DIR = os.path.dirname(os.path.abspath(__file__))

# Paths that write/edit tools cannot touch
_DENIED_PATHS = [
    os.path.join(_HOME_DIR, ".ssh"),
    os.path.join(_HOME_DIR, ".gnupg"),
    os.path.join(_HOME_DIR, ".config", "autostart"),
]

# Shell commands blocked in code (not just in the LLM prompt)
_BLOCKED_SHELL = [
    "sudo ", "sudo\t", "doas ",
    "rm -rf /", "rm -rf /*",
    "dd if=", "mkfs", "> /dev/sd", "> /dev/nvme",
    "chmod 777 /", "chmod -R 777 /",
    "shutdown", "reboot", "init 0", "init 6",
    ":(){ :|:& };:",
    "| bash", "|bash", "| sh ", "|sh ",
    "| zsh", "|zsh",
]


def _validate_path(path, allow_read_only=False):
    """Validate a file path is within the user's home directory.

    Returns (resolved_path, error_string). Error is None if OK.
    """
    resolved = os.path.realpath(os.path.expanduser(path))
    if not resolved.startswith(_HOME_DIR + os.sep) and resolved != _HOME_DIR:
        return None, f"Access denied: path must be under {_HOME_DIR}"
    if not allow_read_only:
        for denied in _DENIED_PATHS:
            if resolved.startswith(denied + os.sep) or resolved == denied:
                return None, f"Access denied: cannot write to {denied}"
    return resolved, None

# Registry of all available tools
TOOLS = {}


def register_tool(name, func, description=""):
    """Register a tool function."""
    TOOLS[name] = {"func": func, "desc": description}


def list_tools():
    """Return list of tool names and descriptions."""
    return {name: info["desc"] for name, info in TOOLS.items()}


def execute_tool(name, args):
    """Execute a named tool with given arguments. Returns (success, result_string)."""
    if name not in TOOLS:
        return False, f"Unknown tool: {name}"
    try:
        result = TOOLS[name]["func"](args)
        return True, str(result)
    except Exception as e:
        return False, f"Tool error: {e}"


def parse_tool_calls(text):
    """Extract tool calls from model output.

    Looks for: <tool name="tool_name">arguments</tool>
    Returns list of (name, args, full_match) tuples and the text with tool calls removed.
    """
    pattern = r'<tool\s+name="([^"]+)">(.*?)</tool>'
    matches = re.findall(pattern, text, re.DOTALL)
    cleaned = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    return matches, cleaned


def format_tool_result(name, result):
    """Format a tool result for feeding back to the model."""
    return f'<tool_result name="{name}">{result}</tool_result>'


# === Built-in tools ===

def tool_shell(args):
    """Run a shell command."""
    args = args.strip()
    if not args:
        return "No command provided."
    # Code-enforced blocklist (not just LLM prompt rules)
    args_lower = args.lower()
    for blocked in _BLOCKED_SHELL:
        if blocked in args_lower:
            return f"Blocked for safety: command contains '{blocked.strip()}'"
    try:
        result = subprocess.run(
            args, shell=True, capture_output=True, text=True,
            timeout=TOOL_TIMEOUT, cwd=os.path.expanduser("~"),
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if not output.strip():
            output = f"(exit code {result.returncode})"
        # Truncate very long output
        if len(output) > 8000:
            output = output[:8000] + "\n... (truncated)"
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"Command timed out after {TOOL_TIMEOUT}s"


def tool_read_file(args):
    """Read a file's contents."""
    path, err = _validate_path(args.strip(), allow_read_only=True)
    if err:
        return err
    if not os.path.isfile(path):
        return f"File not found: {path}"
    try:
        with open(path, "r") as f:
            content = f.read()
        if len(content) > 10000:
            content = content[:10000] + "\n... (truncated)"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def tool_write_file(args):
    """Write content to a file. Format: first line is path, rest is content."""
    lines = args.strip().split("\n", 1)
    if len(lines) < 2:
        return "Usage: first line is file path, remaining lines are content."
    path, err = _validate_path(lines[0].strip())
    if err:
        return err
    content = lines[1]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"Written to {path} ({len(content)} bytes)"
    except Exception as e:
        return f"Error writing file: {e}"


def tool_edit_file(args):
    """Replace a string in a file. Format: line1=path, line2=old string, line3=new string."""
    lines = args.strip().split("\n", 2)
    if len(lines) < 3:
        return "Usage: line1=file path, line2=string to find, line3=replacement string"
    path, err = _validate_path(lines[0].strip())
    if err:
        return err
    old = lines[1]
    new = lines[2]
    if not os.path.isfile(path):
        return f"File not found: {path}"
    try:
        with open(path, "r") as f:
            content = f.read()
        if old not in content:
            return "String to replace not found in file."
        content = content.replace(old, new, 1)
        with open(path, "w") as f:
            f.write(content)
        return f"Edited {path}"
    except Exception as e:
        return f"Error editing file: {e}"


def tool_list_files(args):
    """List directory contents."""
    raw = args.strip() if args.strip() else _HOME_DIR
    path, err = _validate_path(raw, allow_read_only=True)
    if err:
        return err
    if not os.path.isdir(path):
        return f"Not a directory: {path}"
    try:
        entries = sorted(os.listdir(path))
        result = []
        for e in entries[:200]:
            full = os.path.join(path, e)
            marker = "/" if os.path.isdir(full) else ""
            result.append(f"  {e}{marker}")
        out = "\n".join(result)
        if len(entries) > 200:
            out += f"\n  ... and {len(entries) - 200} more"
        return out if out else "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"


def tool_python_exec(args):
    """Execute Python code and return output."""
    code = args.strip()
    if not code:
        return "No code provided."
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True, text=True, timeout=TOOL_TIMEOUT,
            cwd=os.path.expanduser("~"),
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if not output.strip():
            output = f"(exit code {result.returncode})"
        if len(output) > 8000:
            output = output[:8000] + "\n... (truncated)"
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"Execution timed out after {TOOL_TIMEOUT}s"


# === Custom tool loader ===

def load_custom_tools():
    """Load custom tools from bolt/custom_tools/ directory."""
    custom_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_tools")
    if not os.path.isdir(custom_dir):
        return
    for fname in os.listdir(custom_dir):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(custom_dir, fname)
        name = fname[:-3]
        try:
            spec = importlib.util.spec_from_file_location(f"custom_tools.{name}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "run") and hasattr(mod, "TOOL_NAME"):
                desc = getattr(mod, "TOOL_DESC", "Custom tool")
                register_tool(mod.TOOL_NAME, mod.run, desc)
        except Exception as e:
            print(f"  [warn] Failed to load custom tool {fname}: {e}", file=sys.stderr)


# === Register built-in tools ===

register_tool("shell", tool_shell, "Run a shell command")
register_tool("read_file", tool_read_file, "Read a file's contents")
register_tool("write_file", tool_write_file, "Write content to a file (line1=path, rest=content)")
register_tool("edit_file", tool_edit_file, "Edit a file (line1=path, line2=old, line3=new)")
register_tool("list_files", tool_list_files, "List directory contents")
register_tool("python_exec", tool_python_exec, "Execute Python code")

# Load any custom tools
load_custom_tools()
