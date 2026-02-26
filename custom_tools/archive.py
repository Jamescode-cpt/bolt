"""BOLT custom tool — create/extract zip & tar archives.

Uses subprocess zip/unzip/tar. All paths validated under /home/mobilenode/.
No shell=True anywhere. Supports zip, tar.gz, tar.bz2, tar.xz.
"""

import os
import subprocess

TOOL_NAME = "archive"
TOOL_DESC = (
    "Create/extract/list zip and tar archives. "
    'Usage: <tool name="archive">zip out.zip file1 file2</tool> or '
    '<tool name="archive">unzip file.zip [target]</tool> or '
    '<tool name="archive">tar create out.tar.gz dir/</tool> or '
    '<tool name="archive">tar extract file.tar.gz</tool> or '
    '<tool name="archive">list file.zip</tool>'
)

HOME = os.path.expanduser("~")
MAX_OUTPUT = 5000


def _validate_path(path):
    """Validate path is under home directory. Returns (abs_path, error)."""
    expanded = os.path.realpath(os.path.expanduser(path))
    if not expanded.startswith(HOME):
        return None, f"Blocked: {path} is outside ~/. All archive ops restricted to {HOME}/"
    return expanded, None


def _validate_paths(paths):
    """Validate multiple paths. Returns (list_of_abs, error)."""
    result = []
    for p in paths:
        abs_p, err = _validate_path(p)
        if err:
            return None, err
        result.append(abs_p)
    return result, None


def _zip_create(output, files):
    """Create a zip archive."""
    out_abs, err = _validate_path(output)
    if err:
        return err
    abs_files, err = _validate_paths(files)
    if err:
        return err

    if not abs_files:
        return "No input files provided."

    # Check inputs exist
    for f in abs_files:
        if not os.path.exists(f):
            return f"Not found: {f}"

    try:
        cmd = ["zip", "-r", out_abs] + abs_files
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return f"zip failed: {result.stderr.strip()}"
        return f"Created {output} ({os.path.getsize(out_abs)} bytes)"
    except FileNotFoundError:
        return "zip not found. Install with: sudo apt install zip"
    except subprocess.TimeoutExpired:
        return "zip timed out"
    except Exception as e:
        return f"zip error: {e}"


def _zip_extract(archive, target=None):
    """Extract a zip archive."""
    arc_abs, err = _validate_path(archive)
    if err:
        return err
    if not os.path.isfile(arc_abs):
        return f"Archive not found: {archive}"

    if target:
        tgt_abs, err = _validate_path(target)
        if err:
            return err
    else:
        tgt_abs = os.path.dirname(arc_abs)

    try:
        cmd = ["unzip", "-o", arc_abs, "-d", tgt_abs]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return f"unzip failed: {result.stderr.strip()}"
        output = result.stdout.strip()
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n... (truncated)"
        return f"Extracted to {tgt_abs}\n{output}"
    except FileNotFoundError:
        return "unzip not found. Install with: sudo apt install unzip"
    except subprocess.TimeoutExpired:
        return "unzip timed out"
    except Exception as e:
        return f"unzip error: {e}"


def _tar_create(output, source):
    """Create a tar archive (auto-detects compression from extension)."""
    out_abs, err = _validate_path(output)
    if err:
        return err
    src_abs, err = _validate_path(source)
    if err:
        return err
    if not os.path.exists(src_abs):
        return f"Not found: {source}"

    # Determine compression flag
    flags = "cf"
    if output.endswith(".tar.gz") or output.endswith(".tgz"):
        flags = "czf"
    elif output.endswith(".tar.bz2"):
        flags = "cjf"
    elif output.endswith(".tar.xz"):
        flags = "cJf"

    try:
        cmd = ["tar", flags, out_abs, "-C", os.path.dirname(src_abs), os.path.basename(src_abs)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return f"tar create failed: {result.stderr.strip()}"
        return f"Created {output} ({os.path.getsize(out_abs)} bytes)"
    except FileNotFoundError:
        return "tar not found"
    except subprocess.TimeoutExpired:
        return "tar timed out"
    except Exception as e:
        return f"tar error: {e}"


def _tar_extract(archive, target=None):
    """Extract a tar archive."""
    arc_abs, err = _validate_path(archive)
    if err:
        return err
    if not os.path.isfile(arc_abs):
        return f"Archive not found: {archive}"

    if target:
        tgt_abs, err = _validate_path(target)
        if err:
            return err
    else:
        tgt_abs = os.path.dirname(arc_abs)

    try:
        cmd = ["tar", "xf", arc_abs, "-C", tgt_abs]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return f"tar extract failed: {result.stderr.strip()}"
        return f"Extracted {archive} to {tgt_abs}"
    except FileNotFoundError:
        return "tar not found"
    except subprocess.TimeoutExpired:
        return "tar extract timed out"
    except Exception as e:
        return f"tar extract error: {e}"


def _list_archive(archive):
    """List contents of an archive."""
    arc_abs, err = _validate_path(archive)
    if err:
        return err
    if not os.path.isfile(arc_abs):
        return f"Archive not found: {archive}"

    try:
        if archive.endswith(".zip"):
            cmd = ["unzip", "-l", arc_abs]
        else:
            cmd = ["tar", "tf", arc_abs]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
        if result.returncode != 0:
            return f"List failed: {result.stderr.strip()}"
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n... (truncated)"
        return output if output else "Archive is empty"
    except FileNotFoundError:
        return "Archive tool not found"
    except subprocess.TimeoutExpired:
        return "List timed out"
    except Exception as e:
        return f"List error: {e}"


def run(args):
    """Create, extract, or list archives.

    Args formats:
      - 'zip output.zip file1 file2 ...'
      - 'unzip file.zip [target_dir]'
      - 'tar create output.tar.gz source_dir'
      - 'tar extract file.tar.gz [target_dir]'
      - 'list file.zip' or 'list file.tar.gz'
    """
    raw = args.strip() if args else ""
    if not raw:
        return (
            'Usage:\n'
            '  <tool name="archive">zip out.zip file1 file2</tool>\n'
            '  <tool name="archive">unzip file.zip [target]</tool>\n'
            '  <tool name="archive">tar create out.tar.gz dir/</tool>\n'
            '  <tool name="archive">tar extract file.tar.gz</tool>\n'
            '  <tool name="archive">list file.zip</tool>'
        )

    parts = raw.split()
    cmd = parts[0].lower()

    try:
        if cmd == "zip":
            if len(parts) < 3:
                return "Usage: zip output.zip file1 [file2 ...]"
            return _zip_create(parts[1], parts[2:])

        elif cmd == "unzip" or cmd == "extract":
            if len(parts) < 2:
                return "Usage: unzip file.zip [target_dir]"
            archive = parts[1]
            target = parts[2] if len(parts) > 2 else None
            if archive.endswith(".zip"):
                return _zip_extract(archive, target)
            else:
                return _tar_extract(archive, target)

        elif cmd == "tar":
            if len(parts) < 3:
                return "Usage: tar create out.tar.gz dir/ OR tar extract file.tar.gz"
            subcmd = parts[1].lower()
            if subcmd == "create":
                if len(parts) < 4:
                    return "Usage: tar create output.tar.gz source_dir"
                return _tar_create(parts[2], parts[3])
            elif subcmd == "extract":
                target = parts[3] if len(parts) > 3 else None
                return _tar_extract(parts[2], target)
            else:
                return f"Unknown tar subcommand: {subcmd}. Use 'create' or 'extract'."

        elif cmd == "list":
            if len(parts) < 2:
                return "Usage: list file.zip or list file.tar.gz"
            return _list_archive(parts[1])

        else:
            return f"Unknown command: {cmd}. Available: zip, unzip, tar, list"

    except Exception as e:
        return f"archive error: {e}"
