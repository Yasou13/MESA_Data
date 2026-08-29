import hashlib
import json
from typing import Sequence

from mesa_legal_data.publisher.models import SourceChunk


def calculate_content_hash(text: str) -> str:
    """Calculates deterministic SHA256 of text encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calculate_canonical_revision_hash(chunks: Sequence[SourceChunk]) -> str:
    """
    Computes a pure canonical revision hash over ordered source chunks.
    Guarantees:
      - Strictly deterministic
      - Excludes volatile runtime data (timestamps, release_id, session_id, UUIDs)
      - Same canonical chunks -> same revision hash
    """
    if not chunks:
        return hashlib.sha256(b"").hexdigest()

    # Sort chunks deterministically by ordinal and chunk_id
    sorted_chunks = sorted(chunks, key=lambda c: (c.ordinal, c.chunk_id))
    hasher = hashlib.sha256()
    for chunk in sorted_chunks:
        # Feed chunk metadata and content hash
        chunk_repr = f"{chunk.chunk_id}:{chunk.chunk_type}:{chunk.char_start}:{chunk.char_end}:{chunk.content_hash}\n"
        hasher.update(chunk_repr.encode("utf-8"))
    return hasher.hexdigest()


def generate_idempotency_key(
    *,
    tenant_id: str,
    workspace_id: str,
    dataset_id: str,
    document_id: str,
    version_id: str,
    chunk_id: str,
    content_hash: str,
) -> str:
    """
    Generates a stable, canonical idempotency key for MESA v4 mutation.
    Guarantees:
      - Pure function of stable target scope + logical identity + content hash
      - No timestamps, random UUIDs, or release IDs
      - Canonical UTF-8 JSON serialization with sorted keys
    """
    stable_payload = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "dataset_id": dataset_id,
        "document_id": document_id,
        "version_id": version_id,
        "chunk_id": chunk_id,
        "content_hash": content_hash,
    }
    canonical_json = json.dumps(stable_payload, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"mesa-data:{payload_hash}"
