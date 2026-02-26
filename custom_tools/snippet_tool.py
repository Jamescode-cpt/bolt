"""BOLT custom tool — Code snippet manager."""

TOOL_NAME = "snippet"
TOOL_DESC = """Code snippet manager — save, search, retrieve code snippets.
Commands:
  save <name> [lang]\\n<code>  — save a snippet (first line = name + optional lang, rest = code)
  get <name>                  — retrieve a snippet by name
  list                        — list all saved snippets
  search <query>              — search snippets by name, content, or tags
  delete <name>               — delete a snippet
  tags <name> <tag1,tag2>     — add tags to a snippet
Examples:
  <tool name="snippet">save fizzbuzz python
for i in range(1, 101):
    if i % 15 == 0: print("FizzBuzz")
    elif i % 5 == 0: print("Buzz")
    elif i % 3 == 0: print("Fizz")
    else: print(i)</tool>
  <tool name="snippet">get fizzbuzz</tool>
  <tool name="snippet">list</tool>
  <tool name="snippet">search fizz</tool>
  <tool name="snippet">tags fizzbuzz interview,loops</tool>
  <tool name="snippet">delete fizzbuzz</tool>
Persists to ~/bolt/snippets.json."""

import os
import json
import time

SNIPPETS_FILE = os.path.expanduser("~/bolt/snippets.json")


def _load_snippets():
    """Load snippets from JSON file."""
    if not os.path.isfile(SNIPPETS_FILE):
        return {}
    try:
        with open(SNIPPETS_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, IOError):
        return {}


def _save_snippets(snippets):
    """Save snippets to JSON file."""
    try:
        os.makedirs(os.path.dirname(SNIPPETS_FILE), exist_ok=True)
        with open(SNIPPETS_FILE, "w") as f:
            json.dump(snippets, f, indent=2)
        return True
    except IOError as e:
        return str(e)


def _detect_language(code):
    """Simple language detection from code content."""
    code_lower = code.strip().lower()
    indicators = {
        "python": ["def ", "import ", "class ", "print(", "elif ", "self.", "#!/usr/bin/env python", "#!/usr/bin/python"],
        "javascript": ["function ", "const ", "let ", "var ", "console.log", "=>", "require(", "module.exports"],
        "typescript": ["interface ", "type ", ": string", ": number", ": boolean", "export default"],
        "rust": ["fn ", "let mut ", "impl ", "struct ", "enum ", "pub fn", "use std::"],
        "go": ["func ", "package ", "import (", "fmt.Print", "go func"],
        "java": ["public class", "public static void main", "System.out.println", "import java."],
        "c": ["#include <", "int main(", "printf(", "malloc(", "sizeof("],
        "cpp": ["#include <iostream>", "std::", "cout <<", "class ", "namespace "],
        "bash": ["#!/bin/bash", "#!/bin/sh", "echo ", "if [", "fi\n", "done\n"],
        "html": ["<!doctype", "<html", "<div", "<head>", "<body>"],
        "css": ["{", "margin:", "padding:", "display:", "color:"],
        "sql": ["select ", "insert ", "create table", "alter table", "from ", "where "],
        "ruby": ["def ", "end\n", "puts ", "require '", "class "],
        "php": ["<?php", "echo ", "function ", "$_GET", "$_POST"],
    }
    scores = {}
    for lang, patterns in indicators.items():
        score = sum(1 for p in patterns if p.lower() in code_lower)
        if score > 0:
            scores[lang] = score
    if scores:
        return max(scores, key=scores.get)
    return "text"


def _format_timestamp(ts):
    """Format a timestamp for display."""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (TypeError, ValueError, OSError):
        return "unknown"


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    try:
        args_str = args.strip()
        if not args_str:
            return ("Usage:\n"
                    "  save <name> [lang]\\n<code>  — save a snippet\n"
                    "  get <name>                  — retrieve a snippet\n"
                    "  list                        — list all snippets\n"
                    "  search <query>              — search snippets\n"
                    "  delete <name>               — delete a snippet\n"
                    "  tags <name> <tag1,tag2>     — add tags to a snippet")

        # Split into first line and rest (for save command)
        lines = args_str.split("\n", 1)
        first_line = lines[0].strip()
        rest = lines[1] if len(lines) > 1 else ""

        parts = first_line.split(None, 1)
        command = parts[0].lower()
        cmd_rest = parts[1].strip() if len(parts) > 1 else ""

        # Command: list
        if command == "list":
            snippets = _load_snippets()
            if not snippets:
                return "No snippets saved yet. Use 'save <name> [lang]\\n<code>' to save one."

            lines_out = [f"Saved snippets ({len(snippets)}):", ""]
            for name, snip in sorted(snippets.items()):
                lang = snip.get("language", "text")
                created = _format_timestamp(snip.get("created", 0))
                tags = ", ".join(snip.get("tags", [])) if snip.get("tags") else ""
                code_preview = snip.get("code", "").split("\n")[0][:60]
                if len(snip.get("code", "").split("\n")[0]) > 60:
                    code_preview += "..."
                tag_str = f"  [{tags}]" if tags else ""
                lines_out.append(f"  {name} ({lang}) — {created}{tag_str}")
                lines_out.append(f"    {code_preview}")
                lines_out.append("")

            return "\n".join(lines_out)

        # Command: save <name> [lang]\n<code>
        elif command == "save":
            if not cmd_rest:
                return "Usage: save <name> [language]\\n<code>"

            # Parse name and optional language from first line
            name_parts = cmd_rest.split()
            snippet_name = name_parts[0].lower()
            explicit_lang = name_parts[1].lower() if len(name_parts) > 1 else None

            code = rest.strip() if rest.strip() else ""
            if not code:
                return "No code provided. Put the code on lines after the name."

            language = explicit_lang or _detect_language(code)

            snippets = _load_snippets()
            now = time.time()
            is_update = snippet_name in snippets

            snippet = {
                "name": snippet_name,
                "language": language,
                "code": code,
                "tags": snippets.get(snippet_name, {}).get("tags", []) if is_update else [],
                "created": snippets.get(snippet_name, {}).get("created", now) if is_update else now,
                "updated": now,
            }
            snippets[snippet_name] = snippet

            result = _save_snippets(snippets)
            if result is True:
                action = "Updated" if is_update else "Saved"
                return f"{action} snippet '{snippet_name}' ({language}, {len(code)} chars, {code.count(chr(10)) + 1} lines)"
            else:
                return f"Error saving snippet: {result}"

        # Command: get <name>
        elif command == "get":
            if not cmd_rest:
                return "Usage: get <name>"
            snippet_name = cmd_rest.lower()
            snippets = _load_snippets()
            if snippet_name not in snippets:
                # Fuzzy search
                close = [n for n in snippets if snippet_name in n or n in snippet_name]
                hint = f" Did you mean: {', '.join(close)}?" if close else ""
                return f"Snippet '{snippet_name}' not found.{hint}"

            snip = snippets[snippet_name]
            tags = ", ".join(snip.get("tags", [])) if snip.get("tags") else "none"
            created = _format_timestamp(snip.get("created", 0))
            updated = _format_timestamp(snip.get("updated", 0))

            return (f"Snippet: {snippet_name}\n"
                    f"Language: {snip.get('language', 'text')}\n"
                    f"Tags: {tags}\n"
                    f"Created: {created} | Updated: {updated}\n"
                    f"---\n"
                    f"{snip.get('code', '')}")

        # Command: search <query>
        elif command == "search":
            if not cmd_rest:
                return "Usage: search <query>"
            query = cmd_rest.lower()
            snippets = _load_snippets()
            if not snippets:
                return "No snippets saved yet."

            matches = []
            for name, snip in snippets.items():
                score = 0
                if query in name:
                    score += 3
                if query in snip.get("code", "").lower():
                    score += 2
                if query in snip.get("language", "").lower():
                    score += 1
                if any(query in t.lower() for t in snip.get("tags", [])):
                    score += 2
                if score > 0:
                    matches.append((name, snip, score))

            if not matches:
                return f"No snippets matching '{cmd_rest}'."

            matches.sort(key=lambda x: x[2], reverse=True)
            lines_out = [f"Found {len(matches)} snippet(s) matching '{cmd_rest}':", ""]
            for name, snip, score in matches[:20]:
                lang = snip.get("language", "text")
                tags = ", ".join(snip.get("tags", [])) if snip.get("tags") else ""
                code_preview = snip.get("code", "").split("\n")[0][:60]
                tag_str = f"  [{tags}]" if tags else ""
                lines_out.append(f"  {name} ({lang}){tag_str}")
                lines_out.append(f"    {code_preview}")
                lines_out.append("")

            return "\n".join(lines_out)

        # Command: delete <name>
        elif command == "delete":
            if not cmd_rest:
                return "Usage: delete <name>"
            snippet_name = cmd_rest.lower()
            snippets = _load_snippets()
            if snippet_name not in snippets:
                return f"Snippet '{snippet_name}' not found."

            del snippets[snippet_name]
            result = _save_snippets(snippets)
            if result is True:
                return f"Deleted snippet '{snippet_name}'."
            else:
                return f"Error deleting snippet: {result}"

        # Command: tags <name> <tag1,tag2>
        elif command == "tags":
            tag_parts = cmd_rest.split(None, 1)
            if len(tag_parts) < 2:
                return "Usage: tags <name> <tag1,tag2,...>"
            snippet_name = tag_parts[0].lower()
            new_tags = [t.strip().lower() for t in tag_parts[1].split(",") if t.strip()]

            snippets = _load_snippets()
            if snippet_name not in snippets:
                return f"Snippet '{snippet_name}' not found."

            existing_tags = set(snippets[snippet_name].get("tags", []))
            existing_tags.update(new_tags)
            snippets[snippet_name]["tags"] = sorted(existing_tags)
            snippets[snippet_name]["updated"] = time.time()

            result = _save_snippets(snippets)
            if result is True:
                return f"Tags updated for '{snippet_name}': {', '.join(sorted(existing_tags))}"
            else:
                return f"Error updating tags: {result}"

        else:
            return (f"Unknown command: {command}\n"
                    "Commands: save, get, list, search, delete, tags")

    except Exception as e:
        return f"Snippet tool error: {e}"
