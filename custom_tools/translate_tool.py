"""BOLT custom tool — Text translation using free APIs (no API key needed)."""

TOOL_NAME = "translate"
TOOL_DESC = """Text translation using free APIs (MyMemory / LibreTranslate).
Commands:
  <text>                — auto-detect language, translate to English
  to <lang> <text>      — translate to specified language (e.g., to es Hello world)
  detect <text>         — detect language of text
  langs                 — list supported language codes
Examples:
  <tool name="translate">Bonjour le monde</tool>
  <tool name="translate">to es Hello world</tool>
  <tool name="translate">detect こんにちは</tool>
  <tool name="translate">langs</tool>
Rate limited: 1 request per 2 seconds."""

import time

# Rate limiter state
_last_request_time = 0.0

SUPPORTED_LANGS = {
    "af": "Afrikaans", "sq": "Albanian", "ar": "Arabic", "hy": "Armenian",
    "az": "Azerbaijani", "eu": "Basque", "be": "Belarusian", "bg": "Bulgarian",
    "ca": "Catalan", "zh": "Chinese", "hr": "Croatian", "cs": "Czech",
    "da": "Danish", "nl": "Dutch", "en": "English", "et": "Estonian",
    "fi": "Finnish", "fr": "French", "gl": "Galician", "ka": "Georgian",
    "de": "German", "el": "Greek", "he": "Hebrew", "hi": "Hindi",
    "hu": "Hungarian", "is": "Icelandic", "id": "Indonesian", "ga": "Irish",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "lv": "Latvian",
    "lt": "Lithuanian", "mk": "Macedonian", "ms": "Malay", "mt": "Maltese",
    "no": "Norwegian", "fa": "Persian", "pl": "Polish", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sr": "Serbian", "sk": "Slovak",
    "sl": "Slovenian", "es": "Spanish", "sw": "Swahili", "sv": "Swedish",
    "tl": "Tagalog", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian",
    "ur": "Urdu", "vi": "Vietnamese", "cy": "Welsh",
}


def _rate_limit():
    """Enforce 1 request per 2 seconds."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < 2.0:
        time.sleep(2.0 - elapsed)
    _last_request_time = time.time()


def _mymemory_translate(text, source="autodetect", target="en"):
    """Translate using MyMemory API (free, no key needed)."""
    import urllib.request
    import urllib.parse
    import json

    lang_pair = f"{source}|{target}"
    params = urllib.parse.urlencode({"q": text, "langpair": lang_pair})
    url = f"https://api.mymemory.translated.net/get?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": "BOLT/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("responseStatus") == 200:
        translated = data["responseData"]["translatedText"]
        match_quality = data["responseData"].get("match", 0)
        detected = ""
        if source == "autodetect" and "detectedLanguage" in data["responseData"]:
            dl = data["responseData"]["detectedLanguage"]
            detected = dl if isinstance(dl, str) else dl.get("language", "")
        return translated, detected, match_quality
    else:
        raise Exception(data.get("responseDetails", "MyMemory API error"))


def _libre_translate(text, source="auto", target="en"):
    """Translate using LibreTranslate API (free tier)."""
    import urllib.request
    import json

    url = "https://libretranslate.com/translate"
    payload = json.dumps({
        "q": text,
        "source": source,
        "target": target,
        "format": "text",
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "BOLT/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if "translatedText" in data:
        detected = data.get("detectedLanguage", {})
        lang = detected.get("language", "") if isinstance(detected, dict) else ""
        confidence = detected.get("confidence", 0) if isinstance(detected, dict) else 0
        return data["translatedText"], lang, confidence
    else:
        raise Exception(data.get("error", "LibreTranslate API error"))


def _libre_detect(text):
    """Detect language using LibreTranslate API."""
    import urllib.request
    import json

    url = "https://libretranslate.com/detect"
    payload = json.dumps({"q": text}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "BOLT/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if isinstance(data, list) and data:
        return data[0].get("language", "unknown"), data[0].get("confidence", 0)
    raise Exception("LibreTranslate detect failed")


def _translate_with_fallback(text, source="autodetect", target="en"):
    """Try MyMemory first, fall back to LibreTranslate."""
    errors = []

    # Try MyMemory first
    try:
        libre_src = source if source != "autodetect" else "autodetect"
        translated, detected, quality = _mymemory_translate(text, libre_src, target)
        return translated, detected, "MyMemory"
    except Exception as e:
        errors.append(f"MyMemory: {e}")

    # Fall back to LibreTranslate
    try:
        libre_src = source if source != "autodetect" else "auto"
        translated, detected, confidence = _libre_translate(text, libre_src, target)
        return translated, detected, "LibreTranslate"
    except Exception as e:
        errors.append(f"LibreTranslate: {e}")

    return None, None, "Errors:\n" + "\n".join(errors)


def _detect_with_fallback(text):
    """Try LibreTranslate detect first, then MyMemory translate trick."""
    errors = []

    # Try LibreTranslate detect
    try:
        lang, confidence = _libre_detect(text)
        lang_name = SUPPORTED_LANGS.get(lang, lang)
        conf_pct = f"{confidence * 100:.0f}%" if isinstance(confidence, (int, float)) and confidence <= 1 else str(confidence)
        return f"Detected language: {lang} ({lang_name})\nConfidence: {conf_pct}"
    except Exception as e:
        errors.append(f"LibreTranslate: {e}")

    # Fall back: translate to English and check detected language
    try:
        translated, detected, quality = _mymemory_translate(text, "autodetect", "en")
        if detected:
            lang_name = SUPPORTED_LANGS.get(detected, detected)
            return f"Detected language: {detected} ({lang_name})\n(via MyMemory translation)"
        else:
            return f"Could not confidently detect language.\nTranslation to English: {translated}"
    except Exception as e:
        errors.append(f"MyMemory: {e}")

    return "Language detection failed.\n" + "\n".join(errors)


def run(args):
    """args is a string (everything between the <tool> tags). Returns a string."""
    try:
        args = args.strip()
        if not args:
            return ("Usage:\n"
                    "  <text>           — auto-detect and translate to English\n"
                    "  to <lang> <text> — translate to specified language\n"
                    "  detect <text>    — detect language\n"
                    "  langs            — list supported language codes")

        # Command: langs
        if args.lower() == "langs":
            lines = [f"  {code:4s} — {name}" for code, name in sorted(SUPPORTED_LANGS.items())]
            return "Supported language codes:\n" + "\n".join(lines)

        # Command: detect <text>
        if args.lower().startswith("detect "):
            text = args[7:].strip()
            if not text:
                return "Usage: detect <text>"
            _rate_limit()
            return _detect_with_fallback(text)

        # Command: to <lang> <text>
        if args.lower().startswith("to "):
            rest = args[3:].strip()
            parts = rest.split(None, 1)
            if len(parts) < 2:
                return "Usage: to <lang_code> <text>\nExample: to es Hello world"
            target_lang = parts[0].lower()
            text = parts[1]
            if target_lang not in SUPPORTED_LANGS:
                close = [c for c in SUPPORTED_LANGS if c.startswith(target_lang[:2])]
                hint = f" Did you mean: {', '.join(close)}?" if close else ""
                return f"Unknown language code: {target_lang}.{hint}\nUse 'langs' to see supported codes."
            _rate_limit()
            translated, detected, api = _translate_with_fallback(text, "autodetect", target_lang)
            if translated is None:
                return f"Translation failed.\n{api}"
            result = f"Translation ({api}):\n{translated}"
            if detected:
                lang_name = SUPPORTED_LANGS.get(detected, detected)
                result += f"\n\nSource language detected: {detected} ({lang_name})"
            return result

        # Default: auto-detect and translate to English
        text = args
        _rate_limit()
        translated, detected, api = _translate_with_fallback(text, "autodetect", "en")
        if translated is None:
            return f"Translation failed.\n{api}"
        result = f"Translation to English ({api}):\n{translated}"
        if detected:
            lang_name = SUPPORTED_LANGS.get(detected, detected)
            result += f"\n\nSource language detected: {detected} ({lang_name})"
        return result

    except Exception as e:
        return f"Translation error: {e}"
