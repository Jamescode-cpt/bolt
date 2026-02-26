"""BOLT custom tool — image manipulation utilities.

Supports info, resize, convert, thumbnail, and strip operations.
Tries PIL/Pillow first, falls back to ImageMagick CLI, then ffmpeg.
Never overwrites originals — always creates new files.
"""

import os
import re
import time

TOOL_NAME = "image"
TOOL_DESC = (
    "Image manipulation utilities. "
    'Usage: <tool name="image">info /path/to/image.png</tool> — show dimensions, format, size, EXIF. '
    '<tool name="image">resize /path/to/image.png 800x600</tool> — resize image. '
    '<tool name="image">convert /path/to/image.png jpg</tool> — convert format. '
    '<tool name="image">thumbnail /path/to/image.png 200</tool> — create thumbnail. '
    '<tool name="image">strip /path/to/image.png</tool> — strip EXIF metadata.'
)

SAFE_PATH_PREFIX = "/home/mobilenode/"

SUPPORTED_FORMATS = {
    "png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff", "tif", "ico", "ppm", "pgm", "pbm",
}


def _validate_path(filepath):
    """Ensure path is under /home/mobilenode/ and exists."""
    filepath = os.path.expanduser(filepath)
    real = os.path.realpath(filepath)
    if not real.startswith(SAFE_PATH_PREFIX):
        return False, f"Path outside allowed directory: {real}", real
    return True, "", real


def _format_size(size_bytes):
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _get_backend():
    """Detect available image processing backend.

    Returns: ('pil', module), ('magick', path), ('ffmpeg', path), or (None, None)
    """
    # Try PIL/Pillow
    try:
        from PIL import Image
        return "pil", Image
    except ImportError:
        pass

    # Try ImageMagick
    import shutil
    magick = shutil.which("convert")
    # Make sure it's actually ImageMagick, not some other 'convert'
    if magick:
        import subprocess
        try:
            result = subprocess.run(
                [magick, "--version"], capture_output=True, text=True, timeout=5
            )
            if "ImageMagick" in (result.stdout + result.stderr):
                return "magick", magick
        except Exception:
            pass

    # Try ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return "ffmpeg", ffmpeg

    return None, None


def _make_output_path(original, suffix, new_ext=None):
    """Create an output path with a suffix, never overwriting the original."""
    dirpath = os.path.dirname(original)
    basename = os.path.basename(original)
    name, ext = os.path.splitext(basename)
    if new_ext:
        ext = "." + new_ext.lstrip(".")
    output = os.path.join(dirpath, f"{name}_{suffix}{ext}")
    # Avoid collisions
    counter = 1
    while os.path.exists(output):
        output = os.path.join(dirpath, f"{name}_{suffix}_{counter}{ext}")
        counter += 1
    return output


# ── INFO ────────────────────────────────────────────────────────────────────

def _info_pil(filepath, Image):
    """Get image info using PIL."""
    img = Image.open(filepath)
    lines = [
        f"  File: {filepath}",
        f"  Size on disk: {_format_size(os.path.getsize(filepath))}",
        f"  Dimensions: {img.width} x {img.height}",
        f"  Format: {img.format}",
        f"  Mode: {img.mode}",
    ]

    # EXIF data
    try:
        from PIL.ExifTags import TAGS
        exif_data = img.getexif()
        if exif_data:
            lines.append("  EXIF data:")
            count = 0
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                # Truncate long values
                val_str = str(value)
                if len(val_str) > 80:
                    val_str = val_str[:80] + "..."
                lines.append(f"    {tag}: {val_str}")
                count += 1
                if count >= 20:
                    lines.append(f"    ... and more EXIF tags")
                    break
        else:
            lines.append("  EXIF data: none")
    except Exception:
        lines.append("  EXIF data: could not read")

    img.close()
    return "\n".join(lines)


def _info_magick(filepath, magick_path):
    """Get image info using ImageMagick identify."""
    import subprocess
    import shutil
    identify = shutil.which("identify")
    if not identify:
        return None

    try:
        result = subprocess.run(
            [identify, "-verbose", filepath],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            # Parse the verbose output, extract key info
            output = result.stdout
            lines = [f"  File: {filepath}", f"  Size on disk: {_format_size(os.path.getsize(filepath))}"]
            for line in output.split("\n"):
                line = line.strip()
                for key in ("Geometry:", "Format:", "Colorspace:", "Depth:", "Type:"):
                    if line.startswith(key):
                        lines.append(f"  {line}")
            # Check for EXIF
            if "exif:" in output.lower():
                lines.append("  EXIF data: present (use PIL for detailed EXIF)")
            else:
                lines.append("  EXIF data: none")
            return "\n".join(lines)
    except Exception:
        pass
    return None


def _info_ffmpeg(filepath, ffmpeg_path):
    """Get basic image info using ffprobe."""
    import subprocess
    import shutil
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", filepath],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            lines = [f"  File: {filepath}", f"  Size on disk: {_format_size(os.path.getsize(filepath))}"]
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    lines.append(f"  Dimensions: {stream.get('width', '?')} x {stream.get('height', '?')}")
                    lines.append(f"  Format: {stream.get('codec_name', 'unknown')}")
            return "\n".join(lines)
    except Exception:
        pass
    return None


# ── RESIZE ──────────────────────────────────────────────────────────────────

def _resize_pil(filepath, width, height, Image):
    """Resize image using PIL."""
    img = Image.open(filepath)
    resized = img.resize((width, height), Image.LANCZOS)
    output = _make_output_path(filepath, "resized")
    resized.save(output, quality=95)
    resized.close()
    img.close()
    return output


def _resize_magick(filepath, width, height, magick_path):
    """Resize image using ImageMagick."""
    import subprocess
    output = _make_output_path(filepath, "resized")
    result = subprocess.run(
        [magick_path, filepath, "-resize", f"{width}x{height}!", output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ImageMagick error: {result.stderr.strip()}")
    return output


def _resize_ffmpeg(filepath, width, height, ffmpeg_path):
    """Resize image using ffmpeg."""
    import subprocess
    output = _make_output_path(filepath, "resized")
    result = subprocess.run(
        [ffmpeg_path, "-i", filepath, "-vf", f"scale={width}:{height}", "-y", output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr.strip()}")
    return output


# ── CONVERT ─────────────────────────────────────────────────────────────────

def _convert_pil(filepath, target_format, Image):
    """Convert image format using PIL."""
    img = Image.open(filepath)
    # Handle RGBA -> RGB for JPEG
    if target_format.lower() in ("jpg", "jpeg") and img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img.close()
        img = bg
    output = _make_output_path(filepath, "converted", target_format)
    save_format = target_format.upper()
    if save_format == "JPG":
        save_format = "JPEG"
    img.save(output, format=save_format, quality=95)
    img.close()
    return output


def _convert_magick(filepath, target_format, magick_path):
    """Convert image format using ImageMagick."""
    import subprocess
    output = _make_output_path(filepath, "converted", target_format)
    result = subprocess.run(
        [magick_path, filepath, output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ImageMagick error: {result.stderr.strip()}")
    return output


def _convert_ffmpeg(filepath, target_format, ffmpeg_path):
    """Convert image format using ffmpeg."""
    import subprocess
    output = _make_output_path(filepath, "converted", target_format)
    result = subprocess.run(
        [ffmpeg_path, "-i", filepath, "-y", output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr.strip()}")
    return output


# ── THUMBNAIL ───────────────────────────────────────────────────────────────

def _thumbnail_pil(filepath, size, Image):
    """Create thumbnail using PIL."""
    img = Image.open(filepath)
    img.thumbnail((size, size), Image.LANCZOS)
    output = _make_output_path(filepath, f"thumb_{size}")
    img.save(output, quality=90)
    img.close()
    return output


def _thumbnail_magick(filepath, size, magick_path):
    """Create thumbnail using ImageMagick."""
    import subprocess
    output = _make_output_path(filepath, f"thumb_{size}")
    result = subprocess.run(
        [magick_path, filepath, "-thumbnail", f"{size}x{size}", output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ImageMagick error: {result.stderr.strip()}")
    return output


def _thumbnail_ffmpeg(filepath, size, ffmpeg_path):
    """Create thumbnail using ffmpeg."""
    import subprocess
    output = _make_output_path(filepath, f"thumb_{size}")
    # Scale to fit within size x size while preserving aspect ratio
    result = subprocess.run(
        [ffmpeg_path, "-i", filepath, "-vf",
         f"scale='if(gt(iw,ih),{size},-2)':'if(gt(iw,ih),-2,{size})'",
         "-y", output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr.strip()}")
    return output


# ── STRIP METADATA ──────────────────────────────────────────────────────────

def _strip_pil(filepath, Image):
    """Strip EXIF/metadata using PIL."""
    img = Image.open(filepath)
    # Create a new image without EXIF
    data = list(img.getdata())
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    output = _make_output_path(filepath, "stripped")
    # Preserve format
    fmt = img.format or "PNG"
    if fmt == "JPG":
        fmt = "JPEG"
    clean.save(output, format=fmt, quality=95)
    clean.close()
    img.close()
    return output


def _strip_magick(filepath, magick_path):
    """Strip metadata using ImageMagick."""
    import subprocess
    output = _make_output_path(filepath, "stripped")
    result = subprocess.run(
        [magick_path, filepath, "-strip", output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ImageMagick error: {result.stderr.strip()}")
    return output


def _strip_ffmpeg(filepath, ffmpeg_path):
    """Strip metadata using ffmpeg."""
    import subprocess
    output = _make_output_path(filepath, "stripped")
    result = subprocess.run(
        [ffmpeg_path, "-i", filepath, "-map_metadata", "-1", "-y", output],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr.strip()}")
    return output


# ── MAIN DISPATCHER ─────────────────────────────────────────────────────────

_NO_BACKEND_MSG = (
    "No image processing backend found. Install one of these:\n\n"
    "  Python (recommended):\n"
    "    pip install Pillow\n\n"
    "  System packages:\n"
    "    sudo apt install imagemagick    # Debian/Ubuntu\n"
    "    sudo pacman -S imagemagick      # Arch\n\n"
    "  Or ffmpeg:\n"
    "    sudo apt install ffmpeg\n"
    "    sudo pacman -S ffmpeg"
)


def run(args):
    """Image manipulation dispatcher.

    Args is a string: command [filepath] [options]
    """
    args = (args or "").strip()

    if not args:
        return (
            "Usage:\n"
            '  <tool name="image">info /path/to/image.png</tool>\n'
            '  <tool name="image">resize /path/to/image.png 800x600</tool>\n'
            '  <tool name="image">convert /path/to/image.png jpg</tool>\n'
            '  <tool name="image">thumbnail /path/to/image.png 200</tool>\n'
            '  <tool name="image">strip /path/to/image.png</tool>'
        )

    parts = args.split(None, 1)
    command = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    # ── INFO ──
    if command == "info":
        if not rest:
            return "Usage: info <filepath>"
        filepath = rest.strip()

        ok, msg, filepath = _validate_path(filepath)
        if not ok:
            return msg
        if not os.path.isfile(filepath):
            return f"File not found: {filepath}"

        backend, ref = _get_backend()
        try:
            if backend == "pil":
                return f"Image info:\n{_info_pil(filepath, ref)}"
            elif backend == "magick":
                result = _info_magick(filepath, ref)
                if result:
                    return f"Image info (ImageMagick):\n{result}"
                return f"Could not read image info for {filepath}"
            elif backend == "ffmpeg":
                result = _info_ffmpeg(filepath, ref)
                if result:
                    return f"Image info (ffprobe):\n{result}"
                return f"Could not read image info for {filepath}"
            else:
                return _NO_BACKEND_MSG
        except Exception as e:
            return f"Error reading image info: {e}"

    # ── RESIZE ──
    elif command == "resize":
        if not rest:
            return "Usage: resize <filepath> <width>x<height>"
        resize_parts = rest.rsplit(None, 1)
        if len(resize_parts) < 2:
            return "Usage: resize <filepath> <width>x<height>"

        filepath = resize_parts[0].strip()
        dims = resize_parts[1].strip()

        # Parse dimensions
        match = re.match(r'^(\d+)\s*[xX]\s*(\d+)$', dims)
        if not match:
            return f"Invalid dimensions: {dims}. Expected format: 800x600"
        width, height = int(match.group(1)), int(match.group(2))

        if width <= 0 or height <= 0 or width > 20000 or height > 20000:
            return "Dimensions must be between 1 and 20000 pixels."

        ok, msg, filepath = _validate_path(filepath)
        if not ok:
            return msg
        if not os.path.isfile(filepath):
            return f"File not found: {filepath}"

        backend, ref = _get_backend()
        try:
            if backend == "pil":
                output = _resize_pil(filepath, width, height, ref)
            elif backend == "magick":
                output = _resize_magick(filepath, width, height, ref)
            elif backend == "ffmpeg":
                output = _resize_ffmpeg(filepath, width, height, ref)
            else:
                return _NO_BACKEND_MSG

            size = _format_size(os.path.getsize(output))
            return f"Resized to {width}x{height}:\n  Output: {output}\n  Size: {size}"
        except Exception as e:
            return f"Resize error: {e}"

    # ── CONVERT ──
    elif command == "convert":
        if not rest:
            return "Usage: convert <filepath> <format>"
        convert_parts = rest.rsplit(None, 1)
        if len(convert_parts) < 2:
            return "Usage: convert <filepath> <format>  (e.g., convert photo.png jpg)"

        filepath = convert_parts[0].strip()
        target_format = convert_parts[1].strip().lower().lstrip(".")

        if target_format not in SUPPORTED_FORMATS:
            return f"Unsupported format: {target_format}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"

        ok, msg, filepath = _validate_path(filepath)
        if not ok:
            return msg
        if not os.path.isfile(filepath):
            return f"File not found: {filepath}"

        backend, ref = _get_backend()
        try:
            if backend == "pil":
                output = _convert_pil(filepath, target_format, ref)
            elif backend == "magick":
                output = _convert_magick(filepath, target_format, ref)
            elif backend == "ffmpeg":
                output = _convert_ffmpeg(filepath, target_format, ref)
            else:
                return _NO_BACKEND_MSG

            size = _format_size(os.path.getsize(output))
            return f"Converted to {target_format.upper()}:\n  Output: {output}\n  Size: {size}"
        except Exception as e:
            return f"Convert error: {e}"

    # ── THUMBNAIL ──
    elif command == "thumbnail":
        if not rest:
            return "Usage: thumbnail <filepath> [size]  (default: 200)"
        thumb_parts = rest.rsplit(None, 1)

        # Check if last part is a number (size)
        filepath = rest.strip()
        size = 200  # default
        if len(thumb_parts) >= 2:
            try:
                size = int(thumb_parts[-1])
                filepath = thumb_parts[0].strip()
            except ValueError:
                # Last part wasn't a number, treat entire rest as filepath
                filepath = rest.strip()

        if size <= 0 or size > 5000:
            return "Thumbnail size must be between 1 and 5000 pixels."

        ok, msg, filepath = _validate_path(filepath)
        if not ok:
            return msg
        if not os.path.isfile(filepath):
            return f"File not found: {filepath}"

        backend, ref = _get_backend()
        try:
            if backend == "pil":
                output = _thumbnail_pil(filepath, size, ref)
            elif backend == "magick":
                output = _thumbnail_magick(filepath, size, ref)
            elif backend == "ffmpeg":
                output = _thumbnail_ffmpeg(filepath, size, ref)
            else:
                return _NO_BACKEND_MSG

            file_size = _format_size(os.path.getsize(output))
            return f"Thumbnail created ({size}px):\n  Output: {output}\n  Size: {file_size}"
        except Exception as e:
            return f"Thumbnail error: {e}"

    # ── STRIP ──
    elif command == "strip":
        if not rest:
            return "Usage: strip <filepath>"
        filepath = rest.strip()

        ok, msg, filepath = _validate_path(filepath)
        if not ok:
            return msg
        if not os.path.isfile(filepath):
            return f"File not found: {filepath}"

        backend, ref = _get_backend()
        try:
            if backend == "pil":
                output = _strip_pil(filepath, ref)
            elif backend == "magick":
                output = _strip_magick(filepath, ref)
            elif backend == "ffmpeg":
                output = _strip_ffmpeg(filepath, ref)
            else:
                return _NO_BACKEND_MSG

            orig_size = _format_size(os.path.getsize(filepath))
            new_size = _format_size(os.path.getsize(output))
            return f"Metadata stripped:\n  Output: {output}\n  Original size: {orig_size}\n  New size: {new_size}"
        except Exception as e:
            return f"Strip error: {e}"

    else:
        return (
            f"Unknown image command: {command}\n"
            "Available commands: info, resize, convert, thumbnail, strip"
        )
