"""BOLT custom tool: file and string hashing with verification."""

import hashlib
import os

TOOL_NAME = "hash"
TOOL_DESC = (
    "Compute and verify hashes.\n"
    "  <filepath>                    - md5, sha1, sha256 of a file\n"
    "  text <string>                 - hash a string\n"
    "  verify <filepath> <expected>  - verify a file against an expected hash"
)

ALLOWED_ROOT = "/home/mobilenode/"
BLOCK_SIZE = 65536


def _safe_path(path):
    """Resolve and validate that a path lives under the allowed root."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not resolved.startswith(ALLOWED_ROOT):
        raise PermissionError(f"Access denied: path must be under {ALLOWED_ROOT}")
    return resolved


def _hash_bytes(data):
    """Return md5, sha1, sha256 hex digests for raw bytes."""
    return {
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _hash_file(filepath):
    """Stream-hash a file to avoid loading it entirely into memory."""
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(BLOCK_SIZE)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
    return {
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "sha256": sha256.hexdigest(),
    }


def _format_hashes(hashes, label=""):
    """Pretty-print a dict of algorithm->digest."""
    header = f"Hashes for {label}\n" if label else ""
    lines = [f"  {algo}: {digest}" for algo, digest in hashes.items()]
    return header + "\n".join(lines)


def run(args):
    """Entry point called by BOLT tool loop."""
    args = (args or "").strip()
    if not args:
        return "Usage:\n" + TOOL_DESC

    parts = args.split(None, 1)
    command = parts[0].lower()

    # --- hash a string ---
    if command == "text":
        if len(parts) < 2:
            return "Error: provide a string to hash.  Usage: text <string>"
        text = parts[1]
        hashes = _hash_bytes(text.encode("utf-8"))
        return _format_hashes(hashes, label=repr(text))

    # --- verify a file hash ---
    if command == "verify":
        if len(parts) < 2:
            return "Error: Usage: verify <filepath> <expected_hash>"
        verify_parts = parts[1].rsplit(None, 1)
        if len(verify_parts) < 2:
            return "Error: Usage: verify <filepath> <expected_hash>"
        filepath_raw, expected = verify_parts
        try:
            filepath = _safe_path(filepath_raw)
        except PermissionError as e:
            return str(e)
        if not os.path.isfile(filepath):
            return f"Error: '{filepath}' is not a file or does not exist."
        try:
            hashes = _hash_file(filepath)
        except OSError as e:
            return f"Error reading file: {e}"

        expected_lower = expected.lower().strip()
        matched_algo = None
        for algo, digest in hashes.items():
            if digest == expected_lower:
                matched_algo = algo
                break

        if matched_algo:
            return f"MATCH ({matched_algo}): {expected_lower}\n  File: {filepath}"
        else:
            lines = [f"NO MATCH for expected hash: {expected_lower}", f"  File: {filepath}"]
            for algo, digest in hashes.items():
                lines.append(f"  {algo}: {digest}")
            return "\n".join(lines)

    # --- default: treat entire arg string as a filepath ---
    filepath_raw = args
    try:
        filepath = _safe_path(filepath_raw)
    except PermissionError as e:
        return str(e)

    if not os.path.isfile(filepath):
        return f"Error: '{filepath}' is not a file or does not exist."

    try:
        hashes = _hash_file(filepath)
    except OSError as e:
        return f"Error reading file: {e}"

    size = os.path.getsize(filepath)
    return _format_hashes(hashes, label=f"{filepath} ({size:,} bytes)")
