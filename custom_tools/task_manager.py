"""
BOLT Custom Tool: Task Manager
Persistent task list stored in ~/bolt/user_tasks.json
"""

import json
import os
import time

TOOL_NAME = "tasks"
TOOL_DESC = (
    "Manage a personal task list. Commands:\n"
    "  list              - show all tasks\n"
    "  add <title>       - add a new task\n"
    "  done <id>         - mark a task as done\n"
    "  remove <id>       - remove a task"
)

TASKS_FILE = os.path.expanduser("~/bolt/user_tasks.json")


def _load_tasks():
    """Load tasks from disk. Returns a list of task dicts."""
    if not os.path.exists(TASKS_FILE):
        return []
    try:
        with open(TASKS_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, IOError) as e:
        return []


def _save_tasks(tasks):
    """Write tasks to disk atomically."""
    tmp = TASKS_FILE + ".tmp"
    try:
        os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(tasks, f, indent=2)
        os.replace(tmp, TASKS_FILE)
    except IOError as e:
        raise RuntimeError(f"Failed to save tasks: {e}")


def _next_id(tasks):
    """Return the next available task ID."""
    if not tasks:
        return 1
    return max(t.get("id", 0) for t in tasks) + 1


def _format_task(t):
    """Format a single task for display."""
    status = "[done]" if t.get("done") else "[    ]"
    created = t.get("created", "")
    return f"  {t['id']:>4}  {status}  {t['title']}    (created: {created})"


def _cmd_list(tasks):
    if not tasks:
        return "No tasks yet. Use 'add <title>' to create one."
    lines = ["ID    Status  Title"]
    lines.append("-" * 60)
    for t in tasks:
        lines.append(_format_task(t))
    pending = sum(1 for t in tasks if not t.get("done"))
    done = sum(1 for t in tasks if t.get("done"))
    lines.append(f"\n{len(tasks)} total | {pending} pending | {done} done")
    return "\n".join(lines)


def _cmd_add(tasks, title):
    if not title.strip():
        return "Error: task title cannot be empty."
    task = {
        "id": _next_id(tasks),
        "title": title.strip(),
        "done": False,
        "created": time.strftime("%Y-%m-%d %H:%M"),
    }
    tasks.append(task)
    _save_tasks(tasks)
    return f"Added task #{task['id']}: {task['title']}"


def _cmd_done(tasks, id_str):
    try:
        tid = int(id_str)
    except (ValueError, TypeError):
        return "Error: provide a valid numeric task ID."
    for t in tasks:
        if t["id"] == tid:
            if t.get("done"):
                return f"Task #{tid} is already marked done."
            t["done"] = True
            t["completed"] = time.strftime("%Y-%m-%d %H:%M")
            _save_tasks(tasks)
            return f"Task #{tid} marked done: {t['title']}"
    return f"Error: no task with ID {tid}."


def _cmd_remove(tasks, id_str):
    try:
        tid = int(id_str)
    except (ValueError, TypeError):
        return "Error: provide a valid numeric task ID."
    for i, t in enumerate(tasks):
        if t["id"] == tid:
            removed = tasks.pop(i)
            _save_tasks(tasks)
            return f"Removed task #{tid}: {removed['title']}"
    return f"Error: no task with ID {tid}."


def run(args):
    """Entry point called by BOLT tool system."""
    try:
        args = (args or "").strip()
        parts = args.split(None, 1)
        cmd = parts[0].lower() if parts else "list"
        rest = parts[1] if len(parts) > 1 else ""

        tasks = _load_tasks()

        if cmd == "list":
            return _cmd_list(tasks)
        elif cmd == "add":
            return _cmd_add(tasks, rest)
        elif cmd == "done":
            return _cmd_done(tasks, rest.strip())
        elif cmd == "remove":
            return _cmd_remove(tasks, rest.strip())
        else:
            return (
                f"Unknown command: '{cmd}'\n"
                "Available: list, add <title>, done <id>, remove <id>"
            )
    except Exception as e:
        return f"Task manager error: {e}"
