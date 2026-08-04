import puremagic


class ContentTypeError(Exception):
    pass


class SizeLimitError(Exception):
    pass


def detect_mime_type(filepath: str | bytes | bytearray) -> str:
    """
    Detects the MIME type of a file based on magic numbers.
    Defaults to text/plain or unknown if it cannot be determined.
    """
    try:
        if isinstance(filepath, (bytes, bytearray)):
            results = puremagic.magic_string(filepath)
        else:
            results = puremagic.magic_file(str(filepath))

        if results:
            # Sort by confidence and get the most likely
            # The puremagic returns list of Magic objects
            best_match = max(results, key=lambda match: match.confidence)
            return best_match.mime_type
    except puremagic.PureError:
        pass

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
