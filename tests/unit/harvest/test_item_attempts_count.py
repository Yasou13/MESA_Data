from pathlib import Path

import pytest

from mesa_legal_data.harvest.config import load_harvest_config
from mesa_legal_data.harvest.database import get_harvest_connection
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


def test_item_attempts_counter_increments_once_per_runner_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=db_path)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:law:attempt-test",
        document_id="doc-attempt-1",
        family="legislation",
        document_type="law",
        title="Attempt Test Law",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/attempt.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item, _ = enqueue_discovered_document(
        doc,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=db_path,
    )

    # Mock download success and pipeline success
    def mock_collect(item_obj, sources_yaml_path=None):
        return CollectResult(
            artifact_id="art-att-1",
            document_id=item_obj.document_id,
            byte_size=1000,
            duplicate=False,
        )

    def mock_pipeline(artifact_id):
        return PipelineResult(
            artifact_id=artifact_id,
            version_id="ver-1",
            status="approved",
            record_count=1,
            issue_counts={},
        )

    monkeypatch.setattr("mesa_legal_data.harvest.runner.collect_url_item", mock_collect)
    monkeypatch.setattr("mesa_legal_data.harvest.runner.run_pipeline_item", mock_pipeline)

    config = load_harvest_config()
    config.target.minimum_free_disk_bytes = 100

    res = run_harvest_batch(harvest_cfg=config, db_path=db_path)
    assert res["processed"] == 1

    assert item is not None and item.id is not None
    updated_item = get_harvest_item_by_id(item.id, db_path=db_path)
    assert updated_item is not None
    assert updated_item.status == ItemStatus.COMPLETED.value

    # Verify harvest_items.attempts is strictly 1
    assert updated_item.attempts == 1

    # Verify harvest_attempts table has 2 audit stage records (download and pipeline)
    conn = get_harvest_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT stage, result FROM harvest_attempts WHERE item_id = ? ORDER BY id ASC", (item.id,))
    attempts_rows = cursor.fetchall()
    conn.close()

    assert len(attempts_rows) == 2
    assert attempts_rows[0]["stage"] == "download"
    assert attempts_rows[1]["stage"] == "pipeline"
