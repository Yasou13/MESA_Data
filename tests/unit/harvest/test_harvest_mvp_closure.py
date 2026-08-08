from datetime import date
from pathlib import Path

import pytest

from mesa_legal_data.catalog import get_connection, migrate
from mesa_legal_data.harvest.budgets import (
    check_source_circuit_breaker,
    record_circuit_breaker_result,
    reset_circuit_breaker,
)
from mesa_legal_data.harvest.config import load_harvest_config
from mesa_legal_data.harvest.discovery_state import get_discovery_cursor, save_discovery_cursor
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.models import CollectResult, DiscoveredDocument, ItemStatus, PipelineResult
from mesa_legal_data.harvest.queue import (
    acquire_lease_batch,
    enqueue_discovered_document,
    get_harvest_item_by_id,
    recover_expired_leases,
    update_item_status,
)
from mesa_legal_data.harvest.runner import run_harvest_batch
from mesa_legal_data.harvest.selection import SelectionDecision
from mesa_legal_data.parsers.decision import parse_decision_text
from mesa_legal_data.parsers.html import parse_html
from mesa_legal_data.parsers.legislation import parse_legislation_text


def test_crash_while_leased(tmp_path: Path) -> None:
    """Expired item in LEASED status must revert to QUEUED."""
    harvest_db = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=harvest_db)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-08:law:1",
        document_id="doc-crash-leased",
        family="legislation",
        document_type="law",
        title="Test Law",
        publication_date=date(2026, 8, 8),
        document_url="https://resmigazete.gov.tr/1.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item, _ = enqueue_discovered_document(doc, "resmi_gazete", SelectionDecision(True, 100), db_path=harvest_db)
    assert item is not None and item.id is not None

    items = acquire_lease_batch(worker_id="w1", batch_size=1, lease_seconds=-10, db_path=harvest_db)
    assert len(items) == 1
    assert items[0].status == ItemStatus.LEASED.value

    # Simulate crash recovery
    rec = recover_expired_leases(db_path=harvest_db)
    assert rec == 1

    up = get_harvest_item_by_id(item.id, db_path=harvest_db)
    assert up is not None
    assert up.status == ItemStatus.QUEUED.value


def test_crash_while_downloading_without_artifact(tmp_path: Path) -> None:
    """Expired DOWNLOADING item without committed raw artifact must revert to QUEUED."""
    harvest_db = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=harvest_db)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-08:law:2",
        document_id="doc-crash-dl-no-art",
        family="legislation",
        document_type="law",
        title="Test Law",
        publication_date=date(2026, 8, 8),
        document_url="https://resmigazete.gov.tr/2.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item, _ = enqueue_discovered_document(doc, "resmi_gazete", SelectionDecision(True, 100), db_path=harvest_db)
    assert item is not None and item.id is not None

    update_item_status(item.id, ItemStatus.LEASED, db_path=harvest_db)
    update_item_status(item.id, ItemStatus.DOWNLOADING, db_path=harvest_db)

    rec = recover_expired_leases(db_path=harvest_db)
    assert rec == 1

    up = get_harvest_item_by_id(item.id, db_path=harvest_db)
    assert up is not None
    assert up.status == ItemStatus.QUEUED.value


def test_crash_after_artifact_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Expired DOWNLOADING item with committed raw artifact must transition to DOWNLOADED and resume pipeline."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    harvest_db = tmp_path / "harvest.sqlite"
    catalog_db = tmp_path / "catalog.sqlite"
    apply_harvest_migrations(db_path=harvest_db)
    migrate(db_path=catalog_db)

    from mesa_legal_data.catalog import insert_artifact, upsert_document

    # Insert artifact record into catalog
    conn = get_connection(catalog_db)
    upsert_document(
        conn=conn,
        document_id="doc-crash-art",
        family="legislation",
        document_type="law",
        jurisdiction="TR",
        title="Test Law",
        stable_key="doc-crash-art",
        lifecycle_status="fetched",
    )
    insert_artifact(
        conn=conn,
        artifact_id="sha256:art123",
        document_id="doc-crash-art",
        source_id="resmi_gazete",
        source_url="https://resmigazete.gov.tr/1.htm",
        retrieved_at="2026-08-08T00:00:00",
        fetch_method="url",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=100,
        sha256="art123",
        raw_path="raw/test.html",
        etag=None,
        last_modified=None,
        transport_status="verified",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-08:law:3",
        document_id="doc-crash-art",
        family="legislation",
        document_type="law",
        title="Test Law",
        publication_date=date(2026, 8, 8),
        document_url="https://resmigazete.gov.tr/1.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item, _ = enqueue_discovered_document(doc, "resmi_gazete", SelectionDecision(True, 100), db_path=harvest_db)
    assert item is not None and item.id is not None

    update_item_status(item.id, ItemStatus.LEASED, db_path=harvest_db)
    update_item_status(item.id, ItemStatus.DOWNLOADING, artifact_id="sha256:art123", db_path=harvest_db)

    rec = recover_expired_leases(db_path=harvest_db)
    assert rec == 1

    up = get_harvest_item_by_id(item.id, db_path=harvest_db)
    assert up is not None
    assert up.status == ItemStatus.DOWNLOADED.value
    assert up.artifact_id == "sha256:art123"


def test_crash_while_processing_without_canonical(tmp_path: Path) -> None:
    """Expired PROCESSING item without committed canonical version must revert to DOWNLOADED for pipeline rerun."""
    harvest_db = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=harvest_db)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-08:law:4",
        document_id="doc-crash-proc",
        family="legislation",
        document_type="law",
        title="Test Law",
        publication_date=date(2026, 8, 8),
        document_url="https://resmigazete.gov.tr/4.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    item, _ = enqueue_discovered_document(doc, "resmi_gazete", SelectionDecision(True, 100), db_path=harvest_db)
    assert item is not None and item.id is not None

    update_item_status(item.id, ItemStatus.LEASED, db_path=harvest_db)
    update_item_status(item.id, ItemStatus.DOWNLOADING, artifact_id="sha256:artproc", db_path=harvest_db)
    update_item_status(item.id, ItemStatus.DOWNLOADED, db_path=harvest_db)
    update_item_status(item.id, ItemStatus.PROCESSING, db_path=harvest_db)

    rec = recover_expired_leases(db_path=harvest_db)
    assert rec == 1

    up = get_harvest_item_by_id(item.id, db_path=harvest_db)
    assert up is not None
    assert up.status == ItemStatus.DOWNLOADED.value


def test_duplicate_artifact_with_missing_canonical_continues_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a duplicate raw artifact exists but canonical version is missing, runner must not skip pipeline."""
    harvest_db = tmp_path / "harvest.sqlite"
    data_root = tmp_path / "data"
    data_root.mkdir()
    apply_harvest_migrations(db_path=harvest_db)
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    # Mock collect_url_item returning duplicate artifact
    def mock_collect(item, sources_yaml_path=None):
        return CollectResult(artifact_id="sha256:dup123", document_id=item.document_id, byte_size=200, duplicate=True)

    monkeypatch.setattr("mesa_legal_data.harvest.runner.collect_url_item", mock_collect)

    pipe_ran = False

    def mock_run_pipeline(artifact_id):
        nonlocal pipe_ran
        pipe_ran = True
        return PipelineResult(
            artifact_id=artifact_id, version_id="v123", status="approved", record_count=1, issue_counts={}
        )

    monkeypatch.setattr("mesa_legal_data.harvest.runner.run_pipeline_item", mock_run_pipeline)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-08:law:dup",
        document_id="doc-dup-test",
        family="legislation",
        document_type="law",
        title="Dup Law",
        publication_date=date(2026, 8, 8),
        document_url="https://resmigazete.gov.tr/dup.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    enqueue_discovered_document(doc, "resmi_gazete", SelectionDecision(True, 100), db_path=harvest_db)

    cfg = load_harvest_config()
    cfg.target.minimum_free_disk_bytes = 100

    res = run_harvest_batch(harvest_cfg=cfg, db_path=harvest_db, custom_data_root=data_root)
    assert res["processed"] == 1
    assert pipe_ran is True


def test_historical_backfill_and_incremental_cursor_isolation(tmp_path: Path) -> None:
    """Backfill cursor must move backward while incremental high-water mark stays at newest known date."""
    harvest_db = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=harvest_db)

    save_discovery_cursor(
        "resmi_gazete",
        {
            "mode": "backfill",
            "backfill_next_date": "2026-08-07",
            "incremental_high_water_mark": "2026-08-08",
        },
        db_path=harvest_db,
    )

    cur = get_discovery_cursor("resmi_gazete", db_path=harvest_db)
    assert cur is not None
    assert cur["mode"] == "backfill"
    assert cur["backfill_next_date"] == "2026-08-07"
    assert cur["incremental_high_water_mark"] == "2026-08-08"


def test_minified_html_madde_extraction() -> None:
    """Minified HTML with consecutive <p>MADDE...</p> tags must extract all articles without collapsing to zero."""
    minified_html = "<div><p>KANUN</p><p>MADDE 1 – Birinci madde metni.</p><p>MADDE 2 – İkinci madde metni.</p></div>"
    text = parse_html(minified_html)
    assert "MADDE 1" in text
    assert "MADDE 2" in text

    parsed = parse_legislation_text(text)
    assert len(parsed.articles) == 2
    assert parsed.articles[0].article_number == "1"
    assert parsed.articles[1].article_number == "2"


def test_circuit_breaker_cooldown_and_probe() -> None:
    """Circuit breaker must enter timed pause after threshold failures and allow single probe after cooldown."""
    reset_circuit_breaker("test_src")

    # Initially not paused
    paused, probe = check_source_circuit_breaker("test_src")
    assert paused is False
    assert probe is False

    # Simulate circuit breaker probe failure
    record_circuit_breaker_result("test_src", success=False, cooldown_seconds=1800)

    # Immediately after, should be paused
    paused, probe = check_source_circuit_breaker("test_src", cooldown_seconds=1800)
    assert paused is True

    # After probe success, should reset
    record_circuit_breaker_result("test_src", success=True)
    reset_circuit_breaker("test_src")
    paused, probe = check_source_circuit_breaker("test_src")
    assert paused is False


def test_unknown_court_remains_null() -> None:
    """Unknown court in decision text must remain null and never default to YARGITAY."""
    decision_text = "T.C.\nBAŞKANLIK\nEsas No: 2026/100\nKarar No: 2026/200\nKarar Tarihi: 08/08/2026\nKarar metni."
    parsed = parse_decision_text(decision_text)
    assert parsed.court is None


def test_aym_and_danistay_court_detection() -> None:
    """AYM and Danıştay titles must be correctly detected."""
    aym_text = "ANAYASA MAHKEMESİ KARARI\nEsas No: 2026/1\nKarar No: 2026/2"
    parsed_aym = parse_decision_text(aym_text)
    assert parsed_aym.court == "ANAYASA MAHKEMESİ"

    danistay_text = "DANIŞTAY KARARI\nEsas No: 2026/10\nKarar No: 2026/20"
    parsed_dan = parse_decision_text(danistay_text)
    assert parsed_dan.court == "DANIŞTAY"
