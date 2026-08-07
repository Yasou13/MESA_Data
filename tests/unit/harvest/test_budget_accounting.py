from pathlib import Path

import pytest

from mesa_legal_data.harvest.budgets import (
    get_daily_budget_usage,
    get_source_total_raw_bytes,
    get_total_raw_bytes,
)
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


def test_download_success_pipeline_failed_accounting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=db_path)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:law:fail-test",
        document_id="doc-fail-1",
        family="legislation",
        document_type="law",
        title="Fail Test Law",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/fail.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item, _ = enqueue_discovered_document(
        doc,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=db_path,
    )

    # Mock download success (5000 bytes) but pipeline failure
    def mock_collect(item_obj, sources_yaml_path=None):
        return CollectResult(
            artifact_id="art-fail-100",
            document_id=item_obj.document_id,
            byte_size=5000,
            duplicate=False,
        )

    def mock_pipeline(artifact_id):
        return PipelineResult(
            artifact_id=artifact_id,
            version_id=None,
            status="failed",
            record_count=0,
            issue_counts={"PARSING_FAILED": 1},
        )

    monkeypatch.setattr("mesa_legal_data.harvest.runner.collect_url_item", mock_collect)
    monkeypatch.setattr("mesa_legal_data.harvest.runner.run_pipeline_item", mock_pipeline)

    config = load_harvest_config()
    config.target.minimum_free_disk_bytes = 100

    res = run_harvest_batch(harvest_cfg=config, db_path=db_path)
    assert res["processed"] == 1

    assert item is not None and item.id is not None
    updated = get_harvest_item_by_id(item.id, db_path=db_path)
    assert updated is not None
    assert updated.status == ItemStatus.FAILED.value

    # Check total raw bytes & source total raw bytes
    assert get_total_raw_bytes(db_path=db_path) == 5000
    assert get_source_total_raw_bytes("resmi_gazete", db_path=db_path) == 5000

    # Check daily budget usage
    usage = get_daily_budget_usage("resmi_gazete", db_path=db_path)
    assert usage["documents_downloaded"] == 1
    assert usage["raw_bytes_downloaded"] == 5000
    assert usage["pipeline_failed"] == 1
    assert usage["pipeline_success"] == 0
