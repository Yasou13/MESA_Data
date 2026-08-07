from pathlib import Path

import pytest

from mesa_legal_data.harvest.config import load_harvest_config
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.models import (
    DiscoveredDocument,
    ItemStatus,
    PipelineResult,
    SelectionDecision,
)
from mesa_legal_data.harvest.queue import enqueue_discovered_document, get_harvest_item_by_id
from mesa_legal_data.harvest.runner import run_harvest_batch


def test_different_url_same_sha_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    harvest_db = data_root / "harvest" / "harvest.sqlite"
    catalog_db = data_root / "catalog.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    # Initialize catalog and harvest DBs
    from mesa_legal_data.catalog import migrate

    migrate(db_path=catalog_db)
    apply_harvest_migrations(db_path=harvest_db)

    # Mock fetch_url_stream to return identical content for two different URLs
    def mock_fetch_url_stream(url, source_id, document_family, sources_yaml_path=None):
        content = b"<!DOCTYPE html><html><body>MADDE 1 - Bu ayni icerige sahip test belgesidir.</body></html>"
        headers = {"content-type": "text/html"}
        return 200, headers, [content]

    monkeypatch.setattr("mesa_legal_data.sources.manual.fetch_url_stream", mock_fetch_url_stream)

    # Item 1
    doc1 = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:regulation:20260807-1",
        document_id="doc-dup-1",
        family="legislation",
        document_type="regulation",
        title="Doc 1",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/20260807-1.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item1, _ = enqueue_discovered_document(
        doc1,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=harvest_db,
    )

    # Item 2 (Different URL & Document ID, but same stream content)
    doc2 = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:regulation:20260807-2",
        document_id="doc-dup-2",
        family="legislation",
        document_type="regulation",
        title="Doc 2",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/20260807-2.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item2, _ = enqueue_discovered_document(
        doc2,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=harvest_db,
    )

    # Mock pipeline result
    def mock_run_pipeline(artifact_id):
        return PipelineResult(
            artifact_id=artifact_id,
            version_id="v1",
            status="needs_review",
            record_count=1,
            issue_counts={},
        )

    monkeypatch.setattr("mesa_legal_data.harvest.runner.run_pipeline_item", mock_run_pipeline)

    config = load_harvest_config()
    config.target.minimum_free_disk_bytes = 100

    # Run batch 1
    res1 = run_harvest_batch(harvest_cfg=config, db_path=harvest_db, custom_data_root=data_root)
    assert res1["processed"] == 2

    assert item1 is not None and item1.id is not None
    assert item2 is not None and item2.id is not None

    up_item1 = get_harvest_item_by_id(item1.id, db_path=harvest_db)
    up_item2 = get_harvest_item_by_id(item2.id, db_path=harvest_db)

    assert up_item1 is not None
    assert up_item2 is not None

    # First item should be needs_review
    assert up_item1.status == ItemStatus.NEEDS_REVIEW.value

    # Second item should be marked DUPLICATE without retry loop
    assert up_item2.status == ItemStatus.DUPLICATE.value
    assert up_item2.attempts == 1
    assert up_item2.next_retry_at is None
