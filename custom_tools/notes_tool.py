TOOL_NAME = "notes"
TOOL_DESC = """Persistent note-taking system with tags and full-text search.

Commands:
  add <title>\\n<content>   — create a note (first line = title, rest = body)
  list                     — list all notes (id, title, tags, date, preview)
  read <id_or_title>       — read a full note
  edit <id> <title>\\n<new> — update a note
  delete <id>              — delete a note
  search <query>           — full-text search across titles and content
  tag <id> <tag1,tag2>     — add tags to a note
  tags                     — list all tags with note counts

Examples:
  notes add Project Ideas\\nSome thoughts about the next feature...
  notes list
  notes read 1
  notes read "Project Ideas"
  notes edit 1 Updated Title\\nNew content here
  notes delete 3
  notes search feature
  notes tag 1 dev,ideas
  notes tags

Notes are stored in ~/bolt/notes.json."""


import json
import os


_NOTES_FILE = os.path.expanduser("~/bolt/notes.json")
_SAFE_BASE = os.path.realpath(os.path.expanduser("~/"))


def _now_str():
    """Current datetime as ISO string using stdlib only."""
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_notes():
    """Load notes list from disk."""
    if not os.path.exists(_NOTES_FILE):
        return []
    try:
        with open(_NOTES_FILE, "r") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, IOError):
        return []


def _save_notes(notes):
    """Persist notes list to disk."""
    real = os.path.realpath(_NOTES_FILE)
    if not real.startswith(_SAFE_BASE):
        return "Error: Refusing to write outside home directory."
    try:
        os.makedirs(os.path.dirname(_NOTES_FILE), exist_ok=True)
        with open(_NOTES_FILE, "w") as f:
            json.dump(notes, f, indent=2)
        return None
    except IOError as e:
        return f"Error saving notes: {e}"


def _next_id(notes):
    """Get the next auto-increment ID."""
    if not notes:
        return 1
    return max(n.get("id", 0) for n in notes) + 1


def _find_note(notes, id_or_title):
    """Find a note by ID (int) or title (string, case-insensitive)."""
    # Try as ID first
    try:
        target_id = int(id_or_title)
        for n in notes:
            if n.get("id") == target_id:
                return n
    except (ValueError, TypeError):
        pass
    # Try as title (case-insensitive)
    query = str(id_or_title).strip().lower()
    for n in notes:
        if n.get("title", "").lower() == query:
            return n
    # Partial title match
    for n in notes:
        if query in n.get("title", "").lower():
            return n
    return None


def _truncate(text, maxlen=80):
    """Truncate a string to maxlen, add ellipsis if needed."""
    text = text.replace("\n", " ").strip()
    if len(text) <= maxlen:
        return text
    return text[:maxlen - 3] + "..."


def _format_table(header, rows):
    """Simple aligned table."""
    if not rows:
        return "(none)"
    all_rows = [header] + rows
    widths = []
    for col in range(len(header)):
        w = max(len(str(r[col])) if col < len(r) else 0 for r in all_rows)
        widths.append(min(w, 80))
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
            "Notes — persistent note-taking with tags and search.\n"
            "Commands: add | list | read | edit | delete | search | tag | tags\n"
            "Example: notes add My Note Title\\nThe note body goes here."
        )

    # Split into command + rest, preserving newlines in the rest
    first_line_end = args.find("\n")
    if first_line_end == -1:
        first_line = args
        rest_lines = ""
    else:
        first_line = args[:first_line_end]
        rest_lines = args[first_line_end + 1:]

    first_parts = first_line.split(None, 1)
    cmd = first_parts[0].lower()
    cmd_arg = first_parts[1] if len(first_parts) > 1 else ""

    try:
        # ── add ──
        if cmd == "add":
            if not cmd_arg and not rest_lines:
                return "Usage: notes add <title>\\n<content>"
            title = cmd_arg.strip()
            content = rest_lines.strip()
            if not title:
                return "Error: A title is required."
            if not content:
                content = "(empty)"
            notes = _load_notes()
            new_note = {
                "id": _next_id(notes),
                "title": title,
                "content": content,
                "tags": [],
                "created": _now_str(),
                "updated": _now_str(),
            }
            notes.append(new_note)
            err = _save_notes(notes)
            if err:
                return err
            return f"Note #{new_note['id']} created: \"{title}\""

        # ── list ──
        elif cmd == "list":
            notes = _load_notes()
            if not notes:
                return "No notes yet. Use 'notes add <title>\\n<content>' to create one."
            rows = []
            for n in notes:
                nid = str(n.get("id", "?"))
                title = _truncate(n.get("title", "untitled"), 30)
                tags = ", ".join(n.get("tags", [])) or "-"
                date = n.get("created", "?")[:10]
                preview = _truncate(n.get("content", ""), 40)
                rows.append([nid, title, tags, date, preview])
            return "All notes:\n" + _format_table(
                ["ID", "TITLE", "TAGS", "DATE", "PREVIEW"], rows
            )

        # ── read ──
        elif cmd == "read":
            if not cmd_arg:
                return "Usage: notes read <id_or_title>"
            notes = _load_notes()
            # Strip surrounding quotes if present
            lookup = cmd_arg.strip().strip("\"'")
            note = _find_note(notes, lookup)
            if not note:
                return f"Note not found: '{cmd_arg}'. Use 'notes list' to see all notes."
            tags = ", ".join(note.get("tags", [])) or "(none)"
            return (
                f"Note #{note['id']}: {note['title']}\n"
                f"Tags: {tags}\n"
                f"Created: {note.get('created', '?')}  |  Updated: {note.get('updated', '?')}\n"
                f"{'=' * 60}\n"
                f"{note.get('content', '(empty)')}"
            )

        # ── edit ──
        elif cmd == "edit":
            # Format: edit <id> <new title>\n<new content>
            edit_parts = cmd_arg.split(None, 1)
            if not edit_parts:
                return "Usage: notes edit <id> <new title>\\n<new content>"
            try:
                target_id = int(edit_parts[0])
            except ValueError:
                return "Error: First argument to edit must be a note ID (number)."
            new_title = edit_parts[1].strip() if len(edit_parts) > 1 else ""
            new_content = rest_lines.strip()
            if not new_title:
                return "Usage: notes edit <id> <new title>\\n<new content>"
            notes = _load_notes()
            note = None
            for n in notes:
                if n.get("id") == target_id:
                    note = n
                    break
            if not note:
                return f"Note #{target_id} not found."
            note["title"] = new_title
            if new_content:
                note["content"] = new_content
            note["updated"] = _now_str()
            err = _save_notes(notes)
            if err:
                return err
            return f"Note #{target_id} updated: \"{new_title}\""

        # ── delete ──
        elif cmd == "delete":
            if not cmd_arg:
                return "Usage: notes delete <id>"
            try:
                target_id = int(cmd_arg.strip())
            except ValueError:
                return "Error: Argument must be a note ID (number)."
            notes = _load_notes()
            original_len = len(notes)
            notes = [n for n in notes if n.get("id") != target_id]
            if len(notes) == original_len:
                return f"Note #{target_id} not found."
            err = _save_notes(notes)
            if err:
                return err
            return f"Note #{target_id} deleted."

        # ── search ──
        elif cmd == "search":
            if not cmd_arg:
                return "Usage: notes search <query>"
            query = cmd_arg.lower()
            notes = _load_notes()
            matches = []
            for n in notes:
                title = n.get("title", "").lower()
                content = n.get("content", "").lower()
                tags = " ".join(n.get("tags", [])).lower()
                if query in title or query in content or query in tags:
                    matches.append(n)
            if not matches:
                return f"No notes matching '{cmd_arg}'."
            rows = []
            for n in matches:
                nid = str(n.get("id", "?"))
                title = _truncate(n.get("title", "untitled"), 30)
                tags = ", ".join(n.get("tags", [])) or "-"
                date = n.get("created", "?")[:10]
                preview = _truncate(n.get("content", ""), 40)
                rows.append([nid, title, tags, date, preview])
            return f"Search results for '{cmd_arg}':\n" + _format_table(
                ["ID", "TITLE", "TAGS", "DATE", "PREVIEW"], rows
            )

        # ── tag ──
        elif cmd == "tag":
            tag_parts = cmd_arg.split(None, 1)
            if len(tag_parts) < 2:
                return "Usage: notes tag <id> <tag1,tag2,...>"
            try:
                target_id = int(tag_parts[0])
            except ValueError:
                return "Error: First argument must be a note ID (number)."
            new_tags = [t.strip().lower() for t in tag_parts[1].split(",") if t.strip()]
            if not new_tags:
                return "Error: Provide at least one tag (comma-separated)."
            notes = _load_notes()
            note = None
            for n in notes:
                if n.get("id") == target_id:
                    note = n
                    break
            if not note:
                return f"Note #{target_id} not found."
            existing = set(note.get("tags", []))
            added = []
            for tag in new_tags:
                if tag not in existing:
                    existing.add(tag)
                    added.append(tag)
            note["tags"] = sorted(existing)
            note["updated"] = _now_str()
            err = _save_notes(notes)
            if err:
                return err
            if added:
                return f"Added tags to note #{target_id}: {', '.join(added)}\nAll tags: {', '.join(note['tags'])}"
            else:
                return f"Note #{target_id} already has those tags. Current: {', '.join(note['tags'])}"

        # ── tags ──
        elif cmd == "tags":
            notes = _load_notes()
            tag_counts = {}
            for n in notes:
                for t in n.get("tags", []):
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            if not tag_counts:
                return "No tags found. Use 'notes tag <id> <tag1,tag2>' to add tags."
            rows = [[tag, str(count)] for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])]
            return "All tags:\n" + _format_table(["TAG", "NOTES"], rows)

        else:
            return (
                f"Unknown notes command: '{cmd}'\n"
                "Available: add | list | read | edit | delete | search | tag | tags"
            )

    except Exception as e:
        return f"Notes tool error: {e}"
