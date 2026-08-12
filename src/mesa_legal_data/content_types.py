import puremagic


class ContentTypeError(Exception):
    pass


class SizeLimitError(Exception):
    pass


def _sniff_html(data: bytes) -> bool:
    """Check if raw bytes look like HTML content (puremagic often misses HTML)."""
    prefix = data[:512].lstrip().lower()
    return (
        prefix.startswith(b"<!doctype html")
        or prefix.startswith(b"<html")
        or b"<head" in prefix
        or b"<body" in prefix
    )


def detect_mime_type(filepath: str | bytes | bytearray) -> str:
    """
    Detects the MIME type of a file based on magic numbers.
    Falls back to HTML sniffing when puremagic cannot determine the type,
    since puremagic lacks reliable HTML detection (no magic bytes).
    """
    raw_bytes: bytes | None = None

    try:
        if isinstance(filepath, (bytes, bytearray)):
            results = puremagic.magic_string(filepath)
            raw_bytes = bytes(filepath)
        else:
            results = puremagic.magic_file(str(filepath))

        if results:
            best_match = max(results, key=lambda match: match.confidence)
            detected = best_match.mime_type

            # puremagic sometimes returns text/plain for HTML files — double-check
            if detected == "text/plain":
                if raw_bytes is None:
                    with open(filepath, "rb") as f:
                        raw_bytes = f.read(512)
                if _sniff_html(raw_bytes):
                    return "text/html"

            return detected
    except puremagic.PureError:
        pass

    # puremagic couldn't detect anything — try HTML sniffing as last resort
    if raw_bytes is None:
        if isinstance(filepath, (bytes, bytearray)):
            raw_bytes = bytes(filepath)
        else:
            with open(filepath, "rb") as f:
                raw_bytes = f.read(512)

    if _sniff_html(raw_bytes):
        return "text/html"

    return "application/octet-stream"


def validate_file_content(filepath: str, allowed_mimes: list[str], max_bytes: int):
    import os

    size = os.path.getsize(filepath)
    if size == 0:
        raise ContentTypeError("File is empty")

    if size > max_bytes:
        raise SizeLimitError(f"File size {size} exceeds limit {max_bytes}")

    detected = detect_mime_type(filepath)
    if detected not in allowed_mimes:
        raise ContentTypeError(f"Detected MIME {detected} not in allowed list: {allowed_mimes}")

    return detected
