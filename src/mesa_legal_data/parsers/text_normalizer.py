import re
import unicodedata

def normalize_text(text: str) -> str:
    """
    Normalizes legal text while preserving Turkish characters, punctuation, and structure.
    - Applies Unicode NFC normalization.
    - Replaces non-breaking spaces (\u00a0) and zero-width spaces with standard spaces.
    - Strips non-printable control characters except newline (\n) and tab (\t).
    - Normalizes multiple horizontal spaces to single space.
    - Strips trailing whitespace per line.
    """
    if not text:
        return ""

    # NFC Normalization (preserves composite characters like Turkish İ, ı, ş, ğ, vb.)
    text = unicodedata.normalize("NFC", text)

    # Replace non-breaking space & zero-width space
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")

    # Strip null bytes and non-printable control characters except \n and \t
    cleaned_chars = []
    for char in text:
        if char in ("\n", "\t", "\r") or not unicodedata.category(char).startswith("C"):
            cleaned_chars.append(char)
    text = "".join(cleaned_chars)

    # Standardize line endings to \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Replace multiple horizontal spaces/tabs with single space per line
    lines = []
    for line in text.split("\n"):
        line_clean = re.sub(r"[ \t]+", " ", line).strip()
        # Remove spaces before common punctuation marks
        line_clean = re.sub(r"\s+([.,;:!?])", r"\1", line_clean)
        lines.append(line_clean)

    return "\n".join(lines)
