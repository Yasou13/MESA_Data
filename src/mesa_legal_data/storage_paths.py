import re
import unicodedata
from pathlib import Path


class PathSecurityError(Exception):
    pass


def secure_slug(filename: str, max_length: int = 100) -> str:
    """
    Sanitizes a filename to make it a secure slug.
    Rejects null bytes and path traversal characters.
    """
    if "\0" in filename:
        raise PathSecurityError("Null byte detected in filename")

    if "/" in filename or "\\" in filename:
        raise PathSecurityError("Path separators detected in filename")

    if filename == "." or filename == "..":
        raise PathSecurityError("Invalid filename: '.' or '..'")

    # Replace Turkish specific characters
    tr_map = str.maketrans("ğüşöçığĞÜŞÖÇİI", "gusociigusoCII")
    filename = filename.translate(tr_map)

    # Convert to ASCII and remove special characters
    normalized = unicodedata.normalize("NFKD", filename).encode("ASCII", "ignore").decode("utf-8")
    slug = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    slug = re.sub(r"[-\s]+", "-", slug)

    if not slug:
        raise PathSecurityError("Filename resulted in empty slug")

    if len(slug) > max_length:
        slug = slug[:max_length].strip("-")

    return slug


def build_raw_path(
    family: str,
    source: str,
    year: int,
    document_key: str,
    artifact_sha256: str,
    ext: str,
) -> Path:
    """
    Builds a secure raw storage path.
    Format: raw/{family}/{source}/{year}/{document_key}/{artifact_sha256}/payload{ext}
    """
    # Sanitize each component
    safe_family = secure_slug(family)
    safe_source = secure_slug(source)
    safe_key = secure_slug(document_key)
    safe_hash = secure_slug(artifact_sha256)

    if len(safe_hash) != 64:
        raise PathSecurityError("Artifact SHA256 must be exactly 64 characters")

    # Ext should be .pdf, .html etc.
    if not ext.startswith("."):
        ext = "." + ext
    safe_ext = secure_slug(ext.lstrip("."))

    return Path("raw") / safe_family / safe_source / str(year) / safe_key / safe_hash / f"payload.{safe_ext}"
