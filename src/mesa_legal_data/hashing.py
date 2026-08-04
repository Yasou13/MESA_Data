import hashlib
from typing import BinaryIO


def hash_stream(stream: BinaryIO, chunk_size: int = 8192) -> str:
    """
    Reads from a binary stream in chunks and computes the SHA-256 hash.
    """
    hasher = hashlib.sha256()
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        hasher.update(chunk)
    return hasher.hexdigest()
