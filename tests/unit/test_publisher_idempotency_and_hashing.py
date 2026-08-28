from mesa_legal_data.publisher.hashing import (
    calculate_canonical_revision_hash,
    generate_idempotency_key,
)
from mesa_legal_data.publisher.models import SourceChunk


def test_canonical_revision_hash_purity_and_determinism():
    c1 = SourceChunk(
        chunk_id="v1:c1",
        document_id="d1",
        version_id="v1",
        chunk_type="article",
        title="Madde 1",
        char_start=0,
        char_end=50,
        ordinal=1,
        content="İçerik 1",
        content_hash="hash1",
    )
    c2 = SourceChunk(
        chunk_id="v1:c2",
        document_id="d1",
        version_id="v1",
        chunk_type="article",
        title="Madde 2",
        char_start=52,
        char_end=100,
        ordinal=2,
        content="İçerik 2",
        content_hash="hash2",
    )

    hash_a = calculate_canonical_revision_hash([c1, c2])
    hash_b = calculate_canonical_revision_hash([c2, c1])  # Order-independent input gets sorted

    assert hash_a == hash_b
    assert len(hash_a) == 64  # SHA256


def test_idempotency_key_stable_and_free_of_volatile_data():
    key1 = generate_idempotency_key(
        tenant_id="default",
        workspace_id="legal",
        dataset_id="tr_legislation",
        document_id="tr:legislation:law:5237",
        version_id="tr:legislation:law:5237:v1",
        chunk_id="tr:legislation:law:5237:v1:chunk:0001",
        content_hash="abc123def456",
    )

    key2 = generate_idempotency_key(
        tenant_id="default",
        workspace_id="legal",
        dataset_id="tr_legislation",
        document_id="tr:legislation:law:5237",
        version_id="tr:legislation:law:5237:v1",
        chunk_id="tr:legislation:law:5237:v1:chunk:0001",
        content_hash="abc123def456",
    )

    assert key1.startswith("mesa-data:")
    assert key1 == key2

    # Different content hash produces different idempotency key
    key3 = generate_idempotency_key(
        tenant_id="default",
        workspace_id="legal",
        dataset_id="tr_legislation",
        document_id="tr:legislation:law:5237",
        version_id="tr:legislation:law:5237:v1",
        chunk_id="tr:legislation:law:5237:v1:chunk:0001",
        content_hash="different_content_hash",
    )
    assert key1 != key3
