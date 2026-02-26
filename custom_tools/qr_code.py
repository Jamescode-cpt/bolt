"""
BOLT Custom Tool: qr
Generates QR codes as ASCII art. Tries the 'qrcode' library first,
falls back to a simple text-box representation if unavailable.
Handy for sharing URLs/WiFi from the Ally to a phone camera.
"""

TOOL_NAME = "qr"
TOOL_DESC = (
    "Generate QR codes as ASCII art. "
    "Subcommands: generate <text>, url <url>"
)


def run(args):
    """Dispatch subcommand."""
    try:
        parts = args.strip().split(None, 1) if args else []
        subcmd = parts[0].lower() if parts else ""

        if subcmd == "generate":
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: qr generate <text>"
            return _make_qr(parts[1].strip())
        elif subcmd == "url":
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: qr url <url>"
            url = parts[1].strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            return _make_qr(url)
        else:
            return (
                f"Unknown subcommand '{subcmd}'.\n"
                "Available: generate <text>, url <url>"
            )

    except Exception as e:
        return f"qr tool error: {e}"


def _make_qr(data):
    """Try qrcode library, fall back to simple representation."""
    # --- attempt 1: qrcode library (pip install qrcode) ---
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,  # auto-size
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=1,
        )
        qr.add_data(data)
        qr.make(fit=True)

        # Build ASCII from the matrix
        matrix = qr.modules
        lines = []
        for row in matrix:
            line = ""
            for cell in row:
                line += "\u2588\u2588" if cell else "  "
            lines.append(line)

        ascii_art = "\n".join(lines)
        return f"QR Code for: {data}\n\n{ascii_art}\n\n(Scan with your phone camera)"

    except ImportError:
        pass
    except Exception as e:
        # qrcode installed but something went wrong — try fallback
        pass

    # --- attempt 2: segno library ---
    try:
        import segno
        qr = segno.make(data)
        # segno can produce a text representation
        import io
        buf = io.StringIO()
        qr.terminal(out=buf, compact=True)
        art = buf.getvalue()
        return f"QR Code for: {data}\n\n{art}\n(Scan with your phone camera)"

    except ImportError:
        pass
    except Exception:
        pass

    # --- fallback: simple framed text (not scannable, but informative) ---
    return _fallback_qr(data)


def _fallback_qr(data):
    """
    Simple visual representation when no QR library is available.
    Not scannable, but clearly shows the encoded data and
    gives install instructions.
    """
    border_w = max(len(data) + 6, 30)
    top = "\u2554" + "\u2550" * border_w + "\u2557"
    bot = "\u255a" + "\u2550" * border_w + "\u255d"
    side = "\u2551"

    padded = data.center(border_w)
    lines = [
        top,
        f"{side}{'QR CODE (text fallback)'.center(border_w)}{side}",
        f"{side}{' ' * border_w}{side}",
        f"{side}{padded}{side}",
        f"{side}{' ' * border_w}{side}",
        bot,
        "",
        "(No QR library installed — this is a text fallback.)",
        "To get real QR codes, install the library:",
        "  pip install qrcode[pil]",
        "  -- or --",
        "  pip install segno",
    ]
    return "\n".join(lines)
