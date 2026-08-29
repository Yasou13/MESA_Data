import re
import unicodedata

META_CHARSET_PATTERN = re.compile(
    rb"""<meta[^>]+(?:charset\s*=\s*["']?([a-zA-Z0-9_-]+)|content\s*=\s*["'][^"']*charset\s*=\s*([a-zA-Z0-9_-]+))""",
    re.IGNORECASE,
)

# Common Mojibake patterns for Turkish legal texts (UTF-8 decoded as Latin-1/cp1252/cp1254)
MOJIBAKE_PATTERNS = [
    re.compile(r"Ã[§¶¼‡–œ°½¾]"),  # ç, ö, ü, Ç, Ö, Ü, ğ, ı, ş
    re.compile(r"Ä[Ÿ±°]"),  # ğ, ı, İ
    re.compile(r"Å[Ÿž]"),  # ş, Ş
    re.compile(r"[\ufffd]"),  # Unicode replacement character
]


def detect_mojibake(text: str) -> list[str]:
    """
    Detects potential mojibake / corrupted character sequences in text.
    Returns list of issue descriptions if detected.
    """
    issues: list[str] = []
    if not text:
        return issues

    if "\ufffd" in text:
        count = text.count("\ufffd")
        issues.append(f"Unicode replacement character (\\ufffd) found {count} time(s)")

    if "\x00" in text:
        count = text.count("\x00")
        issues.append(f"Null byte (\\x00) found {count} time(s)")

    for pat in MOJIBAKE_PATTERNS[:3]:
        matches = pat.findall(text)
        if matches:
            issues.append(f"Mojibake pattern match: {matches[:5]}")

    # Check for excessive unprintable control characters
    control_count = sum(1 for c in text if c not in ("\n", "\t", "\r") and unicodedata.category(c).startswith("C"))
    if control_count > 0:
        issues.append(f"Unprintable control characters found: {control_count}")

    return issues


def decode_source_bytes(raw_bytes: bytes, is_html: bool = True) -> tuple[str, str]:
    """
    Decodes raw bytes into a Python string preserving Turkish characters
    without silent character deletion (`errors='ignore'` is forbidden).

    Supported encodings:
    - UTF-8 with or without BOM
    - Windows-1254 / cp1254
    - ISO-8859-9 / Latin-5
    - Declared HTML meta charset

    Returns:
        tuple[str, str]: (decoded_text, detected_charset)
    Raises:
        UnicodeDecodeError: If bytes cannot be decoded safely.
    """
    if not raw_bytes:
        return "", "utf-8"

    # 1. UTF-8 BOM detection
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return raw_bytes.decode("utf-8-sig"), "utf-8-sig"

    # 2. HTML meta charset inspection
    if is_html:
        sample = raw_bytes[:4096]
        match = META_CHARSET_PATTERN.search(sample)
        if match:
            charset_bytes = match.group(1) or match.group(2)
            if charset_bytes:
                charset_name = charset_bytes.decode("ascii", errors="ignore").lower().strip()
                if charset_name in ("windows-1254", "cp1254", "1254"):
                    try:
                        return raw_bytes.decode("cp1254"), "windows-1254"
                    except UnicodeDecodeError:
                        pass
                elif charset_name in ("iso-8859-9", "latin5", "8859-9"):
                    try:
                        return raw_bytes.decode("iso-8859-9"), "iso-8859-9"
                    except UnicodeDecodeError:
                        pass
                elif charset_name in ("utf-8", "utf8"):
                    try:
                        return raw_bytes.decode("utf-8"), "utf-8"
                    except UnicodeDecodeError:
                        pass
                else:
                    try:
                        return raw_bytes.decode(charset_name), charset_name
                    except Exception:
                        pass

    # 3. Strict UTF-8 trial
    try:
        return raw_bytes.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    # 4. Turkish fallback trial: cp1254 and iso-8859-9
    try:
        return raw_bytes.decode("cp1254"), "windows-1254"
    except UnicodeDecodeError:
        pass

    try:
        return raw_bytes.decode("iso-8859-9"), "iso-8859-9"
    except UnicodeDecodeError:
        pass

    raise UnicodeDecodeError("utf-8", raw_bytes, 0, len(raw_bytes), "Unable to safely decode source bytes")
