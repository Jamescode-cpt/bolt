"""
BOLT Custom Tool: Backup Manager
Creates, lists, and restores timestamped tar.gz backups.
All paths restricted to /home/mobilenode/.
"""

import os
import tarfile
import time

TOOL_NAME = "backup"
TOOL_DESC = (
    "Create and manage file backups. Commands:\n"
    "  create <path>                - create a timestamped tar.gz backup of path\n"
    "  list                         - list all backups in ~/backups/\n"
    "  restore <backup_file> <dest> - extract a backup to destination"
)

BACKUP_DIR = os.path.expanduser("~/backups")
ALLOWED_PREFIX = "/home/mobilenode/"


def _validate_path(path, label="Path"):
    """Ensure path is under /home/mobilenode/ and exists check is caller's job."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not resolved.startswith(ALLOWED_PREFIX):
        raise ValueError(
            f"{label} '{resolved}' is outside the allowed area ({ALLOWED_PREFIX}). Blocked."
        )
    return resolved


def _ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _human_size(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _cmd_create(path_arg):
    if not path_arg.strip():
        return "Error: provide a path to back up. Example: create ~/bolt"

    source = _validate_path(path_arg, "Source")
    if not os.path.exists(source):
        return f"Error: source path does not exist: {source}"

    _ensure_backup_dir()

    basename = os.path.basename(source.rstrip("/")) or "root"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    archive_name = f"{basename}_{timestamp}.tar.gz"
    archive_path = os.path.join(BACKUP_DIR, archive_name)

    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(source, arcname=basename)
        size = _human_size(os.path.getsize(archive_path))
        return (
            f"Backup created successfully.\n"
            f"  Source:  {source}\n"
            f"  Archive: {archive_path}\n"
            f"  Size:    {size}"
        )
    except PermissionError:
        return f"Error: permission denied reading {source}."
    except Exception as e:
        # Clean up partial archive on failure
        if os.path.exists(archive_path):
            try:
                os.remove(archive_path)
            except OSError:
                pass
        return f"Error creating backup: {e}"


def _cmd_list():
    _ensure_backup_dir()
    entries = []
    try:
        for fname in sorted(os.listdir(BACKUP_DIR)):
            fpath = os.path.join(BACKUP_DIR, fname)
            if os.path.isfile(fpath) and fname.endswith((".tar.gz", ".tgz")):
                size = _human_size(os.path.getsize(fpath))
                mtime = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fpath))
                )
                entries.append(f"  {fname:<45} {size:>10}   {mtime}")
    except OSError as e:
        return f"Error reading backup directory: {e}"

    if not entries:
        return f"No backups found in {BACKUP_DIR}/"

    header = f"Backups in {BACKUP_DIR}/\n" + "-" * 70
    return header + "\n" + "\n".join(entries) + f"\n\n{len(entries)} backup(s) total"


def _cmd_restore(rest):
    parts = rest.strip().split(None, 1)
    if len(parts) < 2:
        return "Error: usage: restore <backup_file> <destination>"

    backup_file, dest = parts[0], parts[1]

    # If backup_file is just a filename, look in BACKUP_DIR
    if not os.path.sep in backup_file:
        backup_path = os.path.join(BACKUP_DIR, backup_file)
    else:
        backup_path = _validate_path(backup_file, "Backup file")

    backup_path = os.path.realpath(backup_path)
    if not backup_path.startswith(ALLOWED_PREFIX):
        return f"Error: backup file path is outside allowed area."

    if not os.path.isfile(backup_path):
        return f"Error: backup file not found: {backup_path}"

    dest = _validate_path(dest, "Destination")

    # Safety: verify it's actually a tar archive
    if not tarfile.is_tarfile(backup_path):
        return f"Error: {backup_path} is not a valid tar archive."

    try:
        os.makedirs(dest, exist_ok=True)

        with tarfile.open(backup_path, "r:gz") as tar:
            # Security check: ensure no paths escape the destination
            for member in tar.getmembers():
                member_path = os.path.realpath(os.path.join(dest, member.name))
                if not member_path.startswith(os.path.realpath(dest)):
                    return (
                        f"Error: archive contains unsafe path '{member.name}' "
                        f"that would escape destination. Aborting."
                    )
            tar.extractall(path=dest)

        return (
            f"Backup restored successfully.\n"
            f"  Archive:     {backup_path}\n"
            f"  Destination: {dest}"
        )
    except PermissionError:
        return f"Error: permission denied writing to {dest}."
    except Exception as e:
        return f"Error restoring backup: {e}"


def run(args):
    """Entry point called by BOLT tool system."""
    try:
        args = (args or "").strip()
        parts = args.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if cmd == "create":
            return _cmd_create(rest)
        elif cmd == "list":
            return _cmd_list()
        elif cmd == "restore":
            return _cmd_restore(rest)
        else:
            return (
                f"Unknown command: '{cmd}'\n"
                "Available: create <path>, list, restore <backup_file> <dest>"
            )
    except ValueError as e:
        return f"Security error: {e}"
    except Exception as e:
        return f"Backup tool error: {e}"
