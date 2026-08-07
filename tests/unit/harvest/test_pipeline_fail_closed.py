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


@pytest.mark.parametrize(
    "pipe_status,expected_item_status",
    [
        ("approved", ItemStatus.COMPLETED),
        ("needs_review", ItemStatus.NEEDS_REVIEW),
        ("rejected", ItemStatus.NEEDS_REVIEW),
        ("failed", ItemStatus.FAILED),
        ("unknown_garbage", ItemStatus.FAILED),
    ],
)
def test_pipeline_status_mapping_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pipe_status: str,
    expected_item_status: ItemStatus,
) -> None:
    db_path = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=db_path)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key=f"rg:2026-08-07:law:{pipe_status}",
        document_id=f"doc-{pipe_status}",
        family="legislation",
        document_type="law",
        title="Test Law",
        publication_date=None,
        document_url=f"https://resmigazete.gov.tr/{pipe_status}.html",
        discovery_page_url="https://resmigazete.gov.tr/index.html",
    )
    item, action = enqueue_discovered_document(
        doc,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100, reasons=("test",)),
        db_path=db_path,
    )
    assert item is not None and item.id is not None

    # Mock collect_url_item and run_pipeline_item
    def mock_collect_url(item_obj, sources_yaml_path=None):
        return CollectResult(
            artifact_id=f"art-{pipe_status}",
            document_id=item_obj.document_id,
            byte_size=1234,
            duplicate=False,
        )

    def mock_run_pipeline(artifact_id):
        return PipelineResult(
            artifact_id=artifact_id,
            version_id="ver-123",
            status=pipe_status,
            record_count=1,
            issue_counts={},
        )

    monkeypatch.setattr("mesa_legal_data.harvest.runner.collect_url_item", mock_collect_url)
    monkeypatch.setattr("mesa_legal_data.harvest.runner.run_pipeline_item", mock_run_pipeline)

    config = load_harvest_config()
    config.target.minimum_free_disk_bytes = 100
    res = run_harvest_batch(harvest_cfg=config, db_path=db_path)
    assert res["processed"] == 1

    updated_item = get_harvest_item_by_id(item.id, db_path=db_path)
    assert updated_item is not None
    assert updated_item.status == expected_item_status.value
