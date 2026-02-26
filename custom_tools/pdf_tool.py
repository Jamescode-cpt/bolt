"""BOLT custom tool — PDF text extraction and info."""

TOOL_NAME = "pdf"
TOOL_DESC = """PDF text extraction and info.
Commands:
  read <filepath>              — extract text from a PDF
  info <filepath>              — show PDF metadata (pages, title, author, etc.)
  search <pattern> <filepath>  — search for text/regex in a PDF
Examples:
  <tool name="pdf">read ~/documents/paper.pdf</tool>
  <tool name="pdf">info ~/documents/paper.pdf</tool>
  <tool name="pdf">search neural network ~/documents/paper.pdf</tool>
Path restricted to /home/mobilenode/. Output truncated to 5000 chars."""

import os

MAX_OUTPUT = 5000
ALLOWED_PREFIX = "/home/mobilenode/"


def _validate_path(filepath):
    """Validate that path is within allowed directory and exists."""
    filepath = os.path.expanduser(filepath.strip())
    filepath = os.path.realpath(filepath)
    if not filepath.startswith(ALLOWED_PREFIX):
        return None, f"Access denied: path must be under {ALLOWED_PREFIX}"
    if not os.path.isfile(filepath):
        return None, f"File not found: {filepath}"
    if not filepath.lower().endswith(".pdf"):
        return None, f"Not a PDF file: {filepath}"
    return filepath, None


def _truncate(text, limit=MAX_OUTPUT):
    """Truncate text with a note if it exceeds the limit."""
    if len(text) > limit:
        return text[:limit] + f"\n\n... [truncated — showing {limit} of {len(text)} chars]"
    return text


def _extract_text_pypdf(filepath):
    """Extract text using pypdf or PyPDF2."""
    # Try pypdf first (newer)
    try:
        import pypdf
        reader = pypdf.PdfReader(filepath)
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(pages) if pages else "(No extractable text found in PDF)"
    except ImportError:
        pass

    # Try PyPDF2
    try:
        import PyPDF2
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"--- Page {i + 1} ---\n{text}")
        return "\n\n".join(pages) if pages else "(No extractable text found in PDF)"
    except ImportError:
        pass

    return None


def _extract_text_cli(filepath):
    """Extract text using pdftotext CLI tool (poppler-utils)."""
    import subprocess
    try:
        result = subprocess.run(
            ["pdftotext", filepath, "-"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        elif result.returncode != 0:
            return None
        else:
            return "(No extractable text found in PDF)"
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return "(pdftotext timed out after 60s)"


def _get_info_pypdf(filepath):
    """Get PDF metadata using pypdf or PyPDF2."""
    # Try pypdf first
    try:
        import pypdf
        reader = pypdf.PdfReader(filepath)
        meta = reader.metadata or {}
        info = {
            "File": filepath,
            "Pages": len(reader.pages),
            "Title": meta.get("/Title", meta.get("title", "N/A")),
            "Author": meta.get("/Author", meta.get("author", "N/A")),
            "Subject": meta.get("/Subject", meta.get("subject", "N/A")),
            "Creator": meta.get("/Creator", meta.get("creator", "N/A")),
            "Producer": meta.get("/Producer", meta.get("producer", "N/A")),
            "Encrypted": reader.is_encrypted,
        }
        # File size
        size = os.path.getsize(filepath)
        if size >= 1_048_576:
            info["Size"] = f"{size / 1_048_576:.1f} MB"
        elif size >= 1024:
            info["Size"] = f"{size / 1024:.1f} KB"
        else:
            info["Size"] = f"{size} bytes"
        return info
    except ImportError:
        pass

    # Try PyPDF2
    try:
        import PyPDF2
        with open(filepath, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            meta = reader.metadata or {}
            info = {
                "File": filepath,
                "Pages": len(reader.pages),
                "Title": meta.get("/Title", "N/A"),
                "Author": meta.get("/Author", "N/A"),
                "Subject": meta.get("/Subject", "N/A"),
                "Creator": meta.get("/Creator", "N/A"),
                "Producer": meta.get("/Producer", "N/A"),
                "Encrypted": reader.is_encrypted,
            }
            size = os.path.getsize(filepath)
            if size >= 1_048_576:
                info["Size"] = f"{size / 1_048_576:.1f} MB"
            elif size >= 1024:
                info["Size"] = f"{size / 1024:.1f} KB"
            else:
                info["Size"] = f"{size} bytes"
            return info
    except ImportError:
        pass

    return None


def _get_info_cli(filepath):
    """Get PDF info using pdfinfo CLI tool (poppler-utils)."""
    import subprocess
    try:
        result = subprocess.run(
            ["pdfinfo", filepath],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            info = {"File": filepath}
            for line in result.stdout.strip().split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    info[key.strip()] = val.strip()
            size = os.path.getsize(filepath)
            if size >= 1_048_576:
                info["Size"] = f"{size / 1_048_576:.1f} MB"
            elif size >= 1024:
                info["Size"] = f"{size / 1024:.1f} KB"
            else:
                info["Size"] = f"{size} bytes"
            return info
        return None
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    try:
        args = args.strip()
        if not args:
            return ("Usage:\n"
                    "  read <filepath>              — extract text from PDF\n"
                    "  info <filepath>              — show PDF metadata\n"
                    "  search <pattern> <filepath>  — search for text in PDF")

        parts = args.split(None, 1)
        command = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        # Command: read <filepath>
        if command == "read":
            if not rest:
                return "Usage: read <filepath>"
            filepath, err = _validate_path(rest)
            if err:
                return err

            # Try Python libraries first
            text = _extract_text_pypdf(filepath)
            if text is not None:
                return _truncate(text)

            # Fall back to CLI
            text = _extract_text_cli(filepath)
            if text is not None:
                return _truncate(text)

            return ("No PDF reader available. Install one of:\n"
                    "  pip install pypdf       (recommended)\n"
                    "  pip install PyPDF2\n"
                    "  sudo apt install poppler-utils  (for pdftotext CLI)")

        # Command: info <filepath>
        elif command == "info":
            if not rest:
                return "Usage: info <filepath>"
            filepath, err = _validate_path(rest)
            if err:
                return err

            # Try Python libraries first
            info = _get_info_pypdf(filepath)
            if info is not None:
                lines = [f"  {k}: {v}" for k, v in info.items()]
                return "PDF Info:\n" + "\n".join(lines)

            # Fall back to CLI
            info = _get_info_cli(filepath)
            if info is not None:
                lines = [f"  {k}: {v}" for k, v in info.items()]
                return "PDF Info:\n" + "\n".join(lines)

            return ("No PDF reader available. Install one of:\n"
                    "  pip install pypdf       (recommended)\n"
                    "  pip install PyPDF2\n"
                    "  sudo apt install poppler-utils  (for pdfinfo CLI)")

        # Command: search <pattern> <filepath>
        elif command == "search":
            if not rest:
                return "Usage: search <pattern> <filepath>"

            # The filepath is the last argument, pattern is everything before it
            # Strategy: try to find a valid .pdf path from the end
            tokens = rest.rsplit(None)
            filepath_candidate = ""
            pattern = ""

            # Walk backwards to find the filepath
            for i in range(len(tokens) - 1, -1, -1):
                candidate = " ".join(tokens[i:])
                candidate_expanded = os.path.realpath(os.path.expanduser(candidate))
                if candidate_expanded.lower().endswith(".pdf") and os.path.isfile(candidate_expanded):
                    filepath_candidate = candidate
                    pattern = " ".join(tokens[:i])
                    break

            if not filepath_candidate or not pattern:
                return "Usage: search <pattern> <filepath>\nCould not identify pattern and filepath. Make sure the filepath ends with .pdf."

            filepath, err = _validate_path(filepath_candidate)
            if err:
                return err

            # Extract text first
            text = _extract_text_pypdf(filepath)
            if text is None:
                text = _extract_text_cli(filepath)
            if text is None:
                return ("No PDF reader available. Install one of:\n"
                        "  pip install pypdf       (recommended)\n"
                        "  pip install PyPDF2\n"
                        "  sudo apt install poppler-utils  (for pdftotext CLI)")

            # Search through the text
            import re
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                return f"Invalid regex pattern: {e}"

            matches = []
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if regex.search(line):
                    # Show context: 1 line before and after
                    start = max(0, i - 1)
                    end = min(len(lines), i + 2)
                    context_lines = lines[start:end]
                    line_nums = list(range(start + 1, end + 1))
                    context = "\n".join(
                        f"  {'>' if j == i + 1 else ' '} {j}: {l}"
                        for j, l in zip(line_nums, context_lines)
                    )
                    matches.append(context)

            if not matches:
                return f"No matches found for '{pattern}' in {filepath}"

            result = f"Found {len(matches)} match(es) for '{pattern}' in {os.path.basename(filepath)}:\n\n"
            result += "\n\n".join(matches[:50])  # Cap at 50 matches
            if len(matches) > 50:
                result += f"\n\n... and {len(matches) - 50} more matches"
            return _truncate(result)

        else:
            # Maybe they just gave a filepath directly — treat as "read"
            filepath, err = _validate_path(args)
            if err is None:
                text = _extract_text_pypdf(filepath)
                if text is None:
                    text = _extract_text_cli(filepath)
                if text is not None:
                    return _truncate(text)
                return ("No PDF reader available. Install one of:\n"
                        "  pip install pypdf       (recommended)\n"
                        "  pip install PyPDF2\n"
                        "  sudo apt install poppler-utils  (for pdftotext CLI)")
            return (f"Unknown command: {command}\n"
                    "Usage: read <filepath> | info <filepath> | search <pattern> <filepath>")

    except Exception as e:
        return f"PDF tool error: {e}"
