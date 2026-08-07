from pathlib import Path

import pytest

from mesa_legal_data.harvest.config import load_harvest_config
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.models import (
    CollectResult,
    DiscoveredDocument,
    ItemStatus,
    PipelineResult,
    SelectionDecision,
)
from mesa_legal_data.harvest.queue import enqueue_discovered_document, get_harvest_item_by_id
from mesa_legal_data.harvest.runner import run_harvest_batch


def test_unsupported_worker_count_raises(tmp_path: Path) -> None:
    cfg_file = tmp_path / "harvest.yaml"
    cfg_file.write_text(
        """
harvest:
  runner:
    worker_count: 2
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="CONFIG_UNSUPPORTED_WORKER_COUNT"):
        load_harvest_config(cfg_file)


def test_source_target_raw_bytes_pauses_only_target_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=db_path)

    # Item for source 1 (resmi_gazete)
    doc1 = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:law:1",
        document_id="doc-src-1",
        family="legislation",
        document_type="law",
        title="Law 1",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/1.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item1, _ = enqueue_discovered_document(
        doc1,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=db_path,
    )

    # Mock download return 1000 bytes
    def mock_collect(item_obj, sources_yaml_path=None):
        return CollectResult(
            artifact_id=f"art-{item_obj.id}",
            document_id=item_obj.document_id,
            byte_size=1000,
            duplicate=False,
        )

    def mock_pipeline(artifact_id):
        return PipelineResult(
            artifact_id=artifact_id,
            version_id="v1",
            status="approved",
            record_count=1,
            issue_counts={},
        )

    monkeypatch.setattr("mesa_legal_data.harvest.runner.collect_url_item", mock_collect)
    monkeypatch.setattr("mesa_legal_data.harvest.runner.run_pipeline_item", mock_pipeline)

    config = load_harvest_config()
    config.target.minimum_free_disk_bytes = 100
    # Set target raw bytes for resmi_gazete to 500 (lower than 1000)
    config.sources["resmi_gazete"].budget.target_raw_bytes = 500

    # Insert fake row where raw_bytes is already 600 (exceeding target)
    from mesa_legal_data.harvest.database import get_harvest_connection

    conn = get_harvest_connection(db_path)
    conn.execute("UPDATE harvest_items SET raw_bytes = 600, artifact_id = 'art-old' WHERE id = ?", (item1.id,))
    conn.commit()
    conn.close()

    res = run_harvest_batch(harvest_cfg=config, db_path=db_path)
    # The runner should skip processing item1 because source target was reached
    assert res["processed"] == 0

    assert item1 is not None and item1.id is not None
    updated = get_harvest_item_by_id(item1.id, db_path=db_path)
    assert updated is not None
    assert updated.status == ItemStatus.QUEUED.value


def test_max_runtime_seconds_leaves_no_stranded_leases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=db_path)

    doc1 = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:law:rt1",
        document_id="doc-rt-1",
        family="legislation",
        document_type="law",
        title="RT 1",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/rt1.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    doc2 = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:law:rt2",
        document_id="doc-rt-2",
        family="legislation",
        document_type="law",
        title="RT 2",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/rt2.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )

    item1, _ = enqueue_discovered_document(
        doc1,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=db_path,
    )
    item2, _ = enqueue_discovered_document(
        doc2,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=db_path,
    )

    # Set max_runtime_seconds = 0 to trigger immediate runtime timeout
    config = load_harvest_config()
    config.target.minimum_free_disk_bytes = 100
    config.runner.max_runtime_seconds = 0

    res = run_harvest_batch(harvest_cfg=config, db_path=db_path)
    assert res.get("stopped_reason", "").startswith("MAX_RUNTIME_REACHED")

    # Verify no leased items remain stranded
    assert item1 is not None and item1.id is not None
    assert item2 is not None and item2.id is not None

    up1 = get_harvest_item_by_id(item1.id, db_path=db_path)
    up2 = get_harvest_item_by_id(item2.id, db_path=db_path)

    assert up1 is not None and up1.status == ItemStatus.QUEUED.value
    assert up2 is not None and up2.status == ItemStatus.QUEUED.value
