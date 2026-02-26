"""BOLT internal state and timeline tracking."""

import uuid
import memory


def new_session_id():
    return uuid.uuid4().hex[:12]


def log(event, details=None):
    """Log an internal event to the timeline."""
    memory.log_event(event, details)


def set_state(key, value):
    memory.kv_set(key, value)


def get_state(key, default=None):
    return memory.kv_get(key, default)


def format_timeline(limit=30):
    """Format timeline for display."""
    rows = memory.get_timeline(limit)
    if not rows:
        return "  No events yet."
    lines = []
    for r in rows:
        detail = f" — {r['details']}" if r["details"] else ""
        lines.append(f"  [{r['ts']}] {r['event']}{detail}")
    return "\n".join(lines)


def format_status(session_id):
    """Format status info for /status command."""
    task = memory.get_active_task()
    summary = memory.get_latest_summary(session_id)
    msg_count = len(memory.get_recent_messages(session_id, limit=9999))

    lines = [
        f"  Session: {session_id}",
        f"  Messages this session: {msg_count}",
    ]
    if task:
        lines.append(f"  Current task: {task['title']} ({task['status']})")
    else:
        lines.append("  Current task: none")
    if summary:
        lines.append(f"  Last summary covers through message #{summary['covers_up_to']}")
    else:
        lines.append("  No summaries yet")
    return "\n".join(lines)


def format_memory(session_id):
    """Format memory contents for /memory command."""
    lines = []
    summary = memory.get_latest_summary(session_id)
    if summary:
        lines.append("  === Summary ===")
        lines.append(f"  {summary['summary']}")
        lines.append("")

    recent = memory.get_recent_messages(session_id, limit=10)
    if recent:
        lines.append("  === Recent Messages ===")
        for r in recent:
            role = r["role"]
            content = r["content"]
            if len(content) > 120:
                content = content[:120] + "..."
            lines.append(f"  [{role}] {content}")
    else:
        lines.append("  No messages yet.")
    return "\n".join(lines)


def format_tasks():
    """Format task list for /task command."""
    tasks = memory.get_all_tasks()
    if not tasks:
        return "  No tasks."
    lines = []
    for t in tasks:
        marker = "✓" if t["status"] == "done" else "✗" if t["status"] == "failed" else "→"
        lines.append(f"  {marker} [{t['id']}] {t['title']} ({t['status']})")
    return "\n".join(lines)
