import os
from pathlib import Path

from mesa_legal_data.content_types import detect_mime_type
from mesa_legal_data.hashing import hash_stream


class TransportValidationError(Exception):
    pass


def validate_transport_integrity(
    file_path: Path,
    expected_sha256: str,
    expected_byte_size: int,
    expected_content_type: str | None = None,
) -> bool:
    """
    Validates transport integrity of a raw artifact.
    """
    if not file_path.exists():
        raise TransportValidationError(f"File {file_path} does not exist")

    actual_size = os.path.getsize(file_path)
    if actual_size == 0:
        raise TransportValidationError(f"File {file_path} is 0 bytes (empty)")

    if actual_size != expected_byte_size:
        raise TransportValidationError(
            f"Byte size mismatch for {file_path.name}: expected {expected_byte_size}, got {actual_size}"
        )

    with open(file_path, "rb") as f:
        actual_sha256 = hash_stream(f)

    if actual_sha256.lower() != expected_sha256.lower():
        raise TransportValidationError(
            f"SHA256 mismatch for {file_path.name}: expected {expected_sha256}, got {actual_sha256}"
        )

    if expected_content_type:
        detected_mime = detect_mime_type(str(file_path))
        if detected_mime != expected_content_type:
            raise TransportValidationError(
                f"Content type mismatch for {file_path.name}: expected {expected_content_type}, got {detected_mime}"
            )

    return True
