"""
BOLT Custom Tool: File Encryption/Decryption
Uses Fernet (cryptography library) if available, falls back to openssl CLI.
Password provided on second line of args. Paths restricted to /home/mobilenode/.
"""

import base64
import hashlib
import os
import subprocess
import shutil

TOOL_NAME = "encrypt"
TOOL_DESC = (
    "Encrypt or decrypt files with a password. Commands:\n"
    "  encrypt <filepath>   - encrypt a file (outputs <filepath>.enc)\n"
    "  decrypt <filepath>   - decrypt a .enc file (removes .enc suffix)\n"
    "Password must be on the second line of the args string."
)

ALLOWED_PREFIX = "/home/mobilenode/"


def _validate_path(path, label="Path"):
    """Ensure path is under /home/mobilenode/."""
    resolved = os.path.realpath(os.path.expanduser(path))
    if not resolved.startswith(ALLOWED_PREFIX):
        raise ValueError(
            f"{label} '{resolved}' is outside the allowed area ({ALLOWED_PREFIX}). Blocked."
        )
    return resolved


def _derive_fernet_key(password, salt=None):
    """Derive a Fernet-compatible key from a password using PBKDF2-HMAC-SHA256.

    Returns (key_bytes, salt_bytes). If salt is None, a new 16-byte random
    salt is generated (for encryption). For decryption, pass the stored salt.
    """
    if salt is None:
        salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return base64.urlsafe_b64encode(key), salt


def _has_fernet():
    """Check if cryptography.fernet is importable."""
    try:
        from cryptography.fernet import Fernet
        return True
    except ImportError:
        return False


def _has_openssl():
    """Check if openssl CLI is available."""
    return shutil.which("openssl") is not None


def _encrypt_fernet(filepath, password):
    from cryptography.fernet import Fernet

    key, salt = _derive_fernet_key(password)
    f = Fernet(key)

    with open(filepath, "rb") as infile:
        data = infile.read()

    encrypted = f.encrypt(data)
    outpath = filepath + ".enc"

    with open(outpath, "wb") as outfile:
        # Write a marker so we know this was Fernet-encrypted
        outfile.write(b"BOLT_FERNET\n")
        # Write the 16-byte salt (needed for PBKDF2 key derivation on decrypt)
        outfile.write(salt)
        outfile.write(encrypted)

    return outpath


def _decrypt_fernet(filepath, password):
    from cryptography.fernet import Fernet

    with open(filepath, "rb") as infile:
        header = infile.readline()
        if header.strip() != b"BOLT_FERNET":
            raise ValueError(
                "This file was not encrypted with BOLT Fernet mode. "
                "It may have been encrypted with openssl."
            )
        # Read the 16-byte PBKDF2 salt stored after the header
        salt = infile.read(16)
        if len(salt) != 16:
            raise ValueError("Corrupt encrypted file: missing PBKDF2 salt.")
        data = infile.read()

    key, _ = _derive_fernet_key(password, salt=salt)
    f = Fernet(key)
    decrypted = f.decrypt(data)

    if filepath.endswith(".enc"):
        outpath = filepath[:-4]
    else:
        outpath = filepath + ".dec"

    with open(outpath, "wb") as outfile:
        outfile.write(decrypted)

    return outpath


def _encrypt_openssl(filepath, password):
    outpath = filepath + ".enc"
    result = subprocess.run(
        [
            "openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "100000",
            "-in", filepath, "-out", outpath, "-pass", "stdin",
        ],
        capture_output=True,
        text=True,
        input=password,
        timeout=60,
    )
    if result.returncode != 0:
        # Clean up partial output
        if os.path.exists(outpath):
            try:
                os.remove(outpath)
            except OSError:
                pass
        raise RuntimeError(f"openssl encrypt failed: {result.stderr.strip()}")
    return outpath


def _decrypt_openssl(filepath, password):
    if filepath.endswith(".enc"):
        outpath = filepath[:-4]
    else:
        outpath = filepath + ".dec"

    result = subprocess.run(
        [
            "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
            "-in", filepath, "-out", outpath, "-pass", "stdin",
        ],
        capture_output=True,
        text=True,
        input=password,
        timeout=60,
    )
    if result.returncode != 0:
        if os.path.exists(outpath):
            try:
                os.remove(outpath)
            except OSError:
                pass
        raise RuntimeError(f"openssl decrypt failed: {result.stderr.strip()}")
    return outpath


def _detect_backend(filepath_for_decrypt=None):
    """
    Choose backend. For decryption, check the file header.
    For encryption, prefer Fernet if available.
    """
    if filepath_for_decrypt and os.path.exists(filepath_for_decrypt):
        try:
            with open(filepath_for_decrypt, "rb") as f:
                header = f.readline().strip()
            if header == b"BOLT_FERNET":
                if _has_fernet():
                    return "fernet"
                else:
                    raise RuntimeError(
                        "File was encrypted with Fernet but cryptography library "
                        "is not installed. Install it with: pip install cryptography"
                    )
        except IOError:
            pass

    if _has_fernet():
        return "fernet"
    if _has_openssl():
        return "openssl"
    return None


def _parse_args(args):
    """Parse args: first line is 'command filepath', second line is password."""
    lines = args.strip().split("\n")
    if len(lines) < 2:
        return None, None, "Error: password required on second line.\nFormat:\n  encrypt <filepath>\n  <password>"
    first_line = lines[0].strip()
    password = lines[1].strip()

    if not password:
        return None, None, "Error: password cannot be empty."

    parts = first_line.split(None, 1)
    if len(parts) < 2:
        return None, None, "Error: provide a command and filepath.\nFormat:\n  encrypt <filepath>\n  <password>"

    cmd = parts[0].lower()
    filepath = parts[1].strip()
    return cmd, filepath, password


def run(args):
    """Entry point called by BOLT tool system."""
    try:
        args = (args or "").strip()
        if not args:
            return (
                "Usage:\n"
                "  encrypt <filepath>\n"
                "  <password>\n\n"
                "  decrypt <filepath>\n"
                "  <password>"
            )

        cmd, filepath, password = _parse_args(args)
        # _parse_args returns error string as third element when first two are None
        if cmd is None and filepath is None:
            return password  # this is the error message

        filepath = _validate_path(filepath, "File")

        if not os.path.isfile(filepath):
            return f"Error: file not found: {filepath}"

        if cmd == "encrypt":
            backend = _detect_backend()
            if backend is None:
                return (
                    "Error: no encryption backend available.\n"
                    "Install cryptography (pip install cryptography) or ensure openssl is in PATH."
                )

            if backend == "fernet":
                outpath = _encrypt_fernet(filepath, password)
                method = "Fernet (AES-128-CBC)"
            else:
                outpath = _encrypt_openssl(filepath, password)
                method = "openssl (AES-256-CBC, PBKDF2)"

            size = os.path.getsize(outpath)
            return (
                f"File encrypted successfully.\n"
                f"  Source:  {filepath}\n"
                f"  Output:  {outpath}\n"
                f"  Method:  {method}\n"
                f"  Size:    {size} bytes\n"
                f"  Note:    Keep your password safe — it cannot be recovered."
            )

        elif cmd == "decrypt":
            backend = _detect_backend(filepath_for_decrypt=filepath)
            if backend is None:
                return (
                    "Error: no decryption backend available.\n"
                    "Install cryptography (pip install cryptography) or ensure openssl is in PATH."
                )

            if backend == "fernet":
                outpath = _decrypt_fernet(filepath, password)
                method = "Fernet"
            else:
                outpath = _decrypt_openssl(filepath, password)
                method = "openssl"

            size = os.path.getsize(outpath)
            return (
                f"File decrypted successfully.\n"
                f"  Source:  {filepath}\n"
                f"  Output:  {outpath}\n"
                f"  Method:  {method}\n"
                f"  Size:    {size} bytes"
            )

        else:
            return f"Unknown command: '{cmd}'\nAvailable: encrypt <filepath>, decrypt <filepath>"

    except ValueError as e:
        return f"Security error: {e}"
    except RuntimeError as e:
        return f"Encryption error: {e}"
    except Exception as e:
        return f"Encrypt tool error: {type(e).__name__}: {e}"
