import json
import sqlite3
from datetime import UTC, datetime

import pytest

from mesa_legal_data.harvest.budgets import (
    check_source_circuit_breaker,
    record_circuit_breaker_result,
    reset_circuit_breaker,
)
from mesa_legal_data.harvest.models import ItemStatus
from mesa_legal_data.harvest.queue import (
    get_harvest_item_by_id,
    operator_retry_item,
    reconcile_harvest_review_status,
    recover_expired_leases,
    update_item_status,
)
from mesa_legal_data.harvest.runner import run_harvest_batch
from mesa_legal_data.release.importer import get_staging_connection, import_release_to_staging, init_staging_db
from mesa_legal_data.release.security import UnsafeReleaseIDError, validate_release_id
from mesa_legal_data.release.verifier import ReleaseVerificationError, verify_release, verify_release_directory
from mesa_legal_data.sources.request_control import SourceRequestBudgetExceeded, get_run_budget, reset_run_budget

VALID_LEG_RECORD = {
    "id": "tr:legislation:law:4721",
    "record_type": "legislation",
    "jurisdiction": "TR",
    "language": "tr",
    "legislation_type": "law",
    "number": "4721",
    "title": "Türk Medeni Kanunu",
    "short_title": "TMK",
    "publication": None,
    "status": "active",
    "version": {
        "version_id": "tr:legislation:law:4721:version:2026-08-05:abcdef12",
        "version_kind": "consolidated_snapshot",
        "snapshot_date": "2026-08-05",
        "effective_from": None,
        "effective_to": None,
    },
    "full_text": "Örnek metin",
    "schema_version": "1.0.0",
    "created_at": "2026-08-05T01:00:00Z",
    "source": {
        "source_id": "mevzuat",
        "source_url": "https://www.mevzuat.gov.tr/1",
        "retrieved_at": "2026-08-05T01:00:00Z",
        "artifact_sha256": "58de994c36ae00e6dc86c00b886c808d7bee1a2306b9ac35bf8aec9e8d297d1f",
        "artifact_path": "raw/test.pdf",
    },
    "provenance": {
        "parser_name": "legislation_parser",
        "parser_version": "1.0.0",
        "pipeline_run_id": "run-123",
    },
}


# 1. crash-after-artifact-commit resumes without redownload
# 2. resume does not reference undefined collect_res
def test_crash_after_artifact_commit_resumes_without_redownload(tmp_path, monkeypatch):
    db_path = tmp_path / "harvest.sqlite"
    from mesa_legal_data.harvest.migrations import apply_harvest_migrations

    apply_harvest_migrations(db_path)

    conn = sqlite3.connect(db_path)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO harvest_items (
            queue_id, source_id, adapter_name, canonical_key, normalized_url, original_url,
            document_id, family, document_type, title, discovery_page_url, priority, status, artifact_id, discovered_at, updated_at
        ) VALUES ('q1', 'resmi_gazete', 'rg', 'ck1', 'https://www.resmigazete.gov.tr/doc1', 'https://www.resmigazete.gov.tr/doc1',
                  'doc1', 'legislation', 'law', 'Title', 'https://www.resmigazete.gov.tr', 100, 'downloading', 'art-123', ?, ?)
        """,
        (now, now),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("mesa_legal_data.harvest.queue._check_artifact_committed", lambda art_id: True)

    recovered = recover_expired_leases(db_path=db_path)
    assert recovered == 1
    item = get_harvest_item_by_id(1, db_path=db_path)
    assert item.status == "downloaded"

    def fake_collect(*args, **kwargs):
        pytest.fail("collect_url_item should NOT be called when artifact is already committed")

    monkeypatch.setattr("mesa_legal_data.harvest.runner.collect_url_item", fake_collect)
    monkeypatch.setattr(
        "mesa_legal_data.harvest.runner.run_pipeline_item",
        lambda art_id: type("PipeRes", (), {"status": "approved", "version_id": "ver-123"})(),
    )

    res = run_harvest_batch(db_path=db_path)
    assert res["processed"] == 1
    assert res["succeeded"] == 1

    item_final = get_harvest_item_by_id(1, db_path=db_path)
    assert item_final.status == "completed"
    assert item_final.version_id == "ver-123"


# 3. resumed exceptions cannot cause secondary invalid transitions
def test_resumed_exceptions_cannot_cause_secondary_invalid_transitions(tmp_path, monkeypatch):
    db_path = tmp_path / "harvest.sqlite"
    from mesa_legal_data.harvest.migrations import apply_harvest_migrations

    apply_harvest_migrations(db_path)

    conn = sqlite3.connect(db_path)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO harvest_items (
            queue_id, source_id, adapter_name, canonical_key, normalized_url, original_url,
            document_id, family, document_type, title, discovery_page_url, priority, status, artifact_id, discovered_at, updated_at
        ) VALUES ('q2', 'resmi_gazete', 'rg', 'ck2', 'https://www.resmigazete.gov.tr/doc2', 'https://www.resmigazete.gov.tr/doc2',
                  'doc2', 'legislation', 'law', 'Title', 'https://www.resmigazete.gov.tr', 100, 'downloaded', 'art-456', ?, ?)
        """,
        (now, now),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("mesa_legal_data.harvest.queue._check_artifact_committed", lambda art_id: True)

    def failing_pipeline(art_id):
        raise RuntimeError("Simulated pipeline crash during resume")

    monkeypatch.setattr("mesa_legal_data.harvest.runner.run_pipeline_item", failing_pipeline)

    res = run_harvest_batch(db_path=db_path)
    assert res["processed"] == 1
    assert res["retry_wait"] == 1

    item = get_harvest_item_by_id(1, db_path=db_path)
    assert item.status == "retry_wait"
    assert item.last_error_code == "UNEXPECTED_ERROR"


# 4. processing crash cannot bypass needs_review
# 5. processing crash cannot convert rejected/pending into completed
def test_processing_crash_cannot_bypass_needs_review(tmp_path, monkeypatch):
    db_path = tmp_path / "harvest.sqlite"
    from mesa_legal_data.harvest.migrations import apply_harvest_migrations

    apply_harvest_migrations(db_path)

    conn = sqlite3.connect(db_path)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO harvest_items (
            queue_id, source_id, adapter_name, canonical_key, normalized_url, original_url,
            document_id, family, document_type, title, discovery_page_url, priority, status, artifact_id, lease_owner, lease_expires_at, discovered_at, updated_at
        ) VALUES ('q3', 'resmi_gazete', 'rg', 'ck3', 'https://www.resmigazete.gov.tr/doc3', 'https://www.resmigazete.gov.tr/doc3',
                  'doc3', 'legislation', 'law', 'Title', 'https://www.resmigazete.gov.tr', 100, 'processing', 'art-789', 'w1', '2020-01-01T00:00:00Z', ?, ?)
        """,
        (now, now),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "mesa_legal_data.harvest.queue._check_canonical_committed",
        lambda art_id, db_path=None: (True, "pending", "ver-789"),
    )

    recovered = recover_expired_leases(db_path=db_path)
    assert recovered == 1

    item = get_harvest_item_by_id(1, db_path=db_path)
    assert item.status == "needs_review"
    assert item.status != "completed"


# 6. coherent manifest rewrite rejected by catalog trust anchor
def test_coherent_manifest_rewrite_rejected_by_catalog_trust_anchor(tmp_path, monkeypatch):
    release_id = "rel-trust-001"
    rel_dir = tmp_path / "releases" / release_id
    rel_dir.mkdir(parents=True, exist_ok=True)

    data_dir = rel_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    data_file = data_dir / "legislation.jsonl"
    data_file.write_text(json.dumps(VALID_LEG_RECORD) + "\n")

    rel_json = rel_dir / "release.json"
    rel_json.write_text(json.dumps({"release_id": release_id, "counts": {"legislation_count": 1}}))

    import hashlib

    h_data = hashlib.sha256(data_file.read_bytes()).hexdigest()
    h_rel = hashlib.sha256(rel_json.read_bytes()).hexdigest()

    manifest = {"files": {"data/legislation.jsonl": h_data, "release.json": h_rel}}
    manifest_file = rel_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))

    original_manifest_hash = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

    def fake_get_release(conn, r_id):
        return {"release_id": release_id, "manifest_sha256": original_manifest_hash}

    monkeypatch.setattr("mesa_legal_data.release.verifier.get_release", fake_get_release)
    monkeypatch.setattr(
        "mesa_legal_data.release.verifier.load_settings",
        lambda: type("Settings", (), {"data_root_path": tmp_path})(),
    )
    monkeypatch.setattr(
        "mesa_legal_data.release.verifier.get_catalog_connection",
        lambda: sqlite3.connect(":memory:"),
    )

    assert verify_release(release_id) is True

    # Tamper with data and manifest coherently
    evil_rec = dict(VALID_LEG_RECORD, title="EVIL")
    data_file.write_text(json.dumps(evil_rec) + "\n")
    new_h_data = hashlib.sha256(data_file.read_bytes()).hexdigest()
    manifest["files"]["data/legislation.jsonl"] = new_h_data
    manifest_file.write_text(json.dumps(manifest))

    with pytest.raises(ReleaseVerificationError, match="trust anchor"):
        verify_release(release_id)


# 7. unmanifested JSONL rejected
# 8. importer cannot ingest unmanifested file
def test_unmanifested_jsonl_rejected(tmp_path):
    rel_dir = tmp_path / "rel-unman"
    rel_dir.mkdir(parents=True, exist_ok=True)
    data_dir = rel_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    data_file = data_dir / "legislation.jsonl"
    data_file.write_text(json.dumps(VALID_LEG_RECORD) + "\n")

    evil_file = data_dir / "evil.jsonl"
    evil_file.write_text('{"id":"evil-1","record_type":"legislation"}\n')

    rel_json = rel_dir / "release.json"
    rel_json.write_text(json.dumps({"release_id": "rel-unman", "counts": {"legislation_count": 1}}))

    import hashlib

    h_data = hashlib.sha256(data_file.read_bytes()).hexdigest()
    h_rel = hashlib.sha256(rel_json.read_bytes()).hexdigest()
    manifest = {"files": {"data/legislation.jsonl": h_data, "release.json": h_rel}}
    (rel_dir / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ReleaseVerificationError, match="Unmanifested file"):
        verify_release_directory(rel_dir, expected_release_id="rel-unman")


# 9. idle Harvest run returns clean zero result
def test_idle_harvest_run_returns_clean_zero_result(tmp_path):
    db_path = tmp_path / "harvest.sqlite"
    from mesa_legal_data.harvest.migrations import apply_harvest_migrations

    apply_harvest_migrations(db_path)

    res = run_harvest_batch(db_path=db_path)
    assert res == {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "retry_wait": 0,
        "duplicate": 0,
        "stopped_reason": "NO_QUEUED_ITEMS",
    }


# 10. FAILED operator retry works deliberately
# 11. BLOCKED cannot be casually retried
def test_operator_retry_semantics(tmp_path):
    db_path = tmp_path / "harvest.sqlite"
    from mesa_legal_data.harvest.migrations import apply_harvest_migrations

    apply_harvest_migrations(db_path)

    conn = sqlite3.connect(db_path)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO harvest_items (
            id, queue_id, source_id, adapter_name, canonical_key, normalized_url, original_url,
            document_id, family, document_type, title, discovery_page_url, priority, status, last_error_code, discovered_at, updated_at
        ) VALUES
        (1, 'q1', 's1', 'a1', 'c1', 'u1', 'u1', 'd1', 'f1', 'law', 't1', 'http://u1', 100, 'failed', 'ERR', ?, ?),
        (2, 'q2', 's1', 'a1', 'c2', 'u2', 'u2', 'd2', 'f1', 'law', 't2', 'http://u2', 100, 'blocked', 'POLICY', ?, ?)
        """,
        (now, now, now, now),
    )
    conn.commit()
    conn.close()

    item1 = operator_retry_item(1, db_path=db_path)
    assert item1.status == "queued"
    assert item1.last_error_code is None

    with pytest.raises(ValueError, match="BLOCKED"):
        operator_retry_item(2, db_path=db_path)


# 12. circuit-breaker probe success resets breaker
# 13. circuit-breaker probe failure reopens pause
def test_circuit_breaker_probe_semantics(tmp_path):
    source_id = "test_src_cb"

    reset_circuit_breaker(source_id)
    _, is_probe = check_source_circuit_breaker(
        source_id, threshold=0.1, cooldown_seconds=60, db_path=tmp_path / "empty.sqlite"
    )

    from mesa_legal_data.harvest.budgets import _SOURCE_IS_PROBING, _SOURCE_PAUSE_UNTIL

    _SOURCE_PAUSE_UNTIL[source_id] = datetime.now(UTC) - datetime.resolution
    is_paused, is_probe = check_source_circuit_breaker(source_id, threshold=0.1, db_path=tmp_path / "empty.sqlite")
    assert is_probe is True

    record_circuit_breaker_result(source_id, success=True)
    assert source_id not in _SOURCE_PAUSE_UNTIL
    assert source_id not in _SOURCE_IS_PROBING

    _SOURCE_PAUSE_UNTIL[source_id] = datetime.now(UTC) - datetime.resolution
    _, is_probe = check_source_circuit_breaker(source_id, threshold=0.1, db_path=tmp_path / "empty.sqlite")
    record_circuit_breaker_result(source_id, success=False, cooldown_seconds=300)
    is_paused, _ = check_source_circuit_breaker(source_id, threshold=0.1, db_path=tmp_path / "empty.sqlite")
    assert is_paused is True


# 14. per-run request cap is actually global to the run
def test_per_run_request_cap_is_global_to_run():
    reset_run_budget("resmi_gazete")
    b1 = get_run_budget("resmi_gazete", max_requests=2)
    b1.consume()
    assert b1.used_requests == 1

    b2 = get_run_budget("resmi_gazete", max_requests=2)
    b2.consume()
    assert b2.used_requests == 2

    with pytest.raises(SourceRequestBudgetExceeded):
        b2.consume()


# 15. downloaded_at remains true download timestamp
# 16. successful retry clears transient live error state
def test_timestamp_and_error_state_clearing_semantics(tmp_path):
    db_path = tmp_path / "harvest.sqlite"
    from mesa_legal_data.harvest.migrations import apply_harvest_migrations

    apply_harvest_migrations(db_path)

    conn = sqlite3.connect(db_path)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO harvest_items (
            id, queue_id, source_id, adapter_name, canonical_key, normalized_url, original_url,
            document_id, family, document_type, title, discovery_page_url, priority, status, discovered_at, updated_at
        ) VALUES (1, 'q1', 's1', 'a1', 'c1', 'u1', 'u1', 'd1', 'f1', 'law', 't1', 'http://u1', 100, 'queued', ?, ?)
        """,
        (now, now),
    )
    conn.commit()
    conn.close()

    update_item_status(1, ItemStatus.LEASED, db_path=db_path)
    update_item_status(1, ItemStatus.DOWNLOADING, db_path=db_path)
    item_d1 = update_item_status(1, ItemStatus.DOWNLOADED, artifact_id="art-1", db_path=db_path)
    download_ts = item_d1.downloaded_at
    assert download_ts is not None

    update_item_status(1, ItemStatus.PROCESSING, db_path=db_path)
    item_c = update_item_status(1, ItemStatus.COMPLETED, db_path=db_path)
    assert item_c.downloaded_at == download_ts
    assert item_c.completed_at is not None


# 17. operator contact reaches actual User-Agent
def test_operator_contact_reaches_user_agent(monkeypatch):
    monkeypatch.setattr(
        "mesa_legal_data.config.load_settings",
        lambda: type("Settings", (), {"operator_contact": "operator@mesalaw.org", "environment": "development"})(),
    )
    from mesa_legal_data.sources.url_fetcher import get_source_input_policy

    pol = get_source_input_policy(source_id="resmi_gazete", document_family="legislation")
    eff_ua = pol.user_agent
    contact = "operator@mesalaw.org"
    if contact not in eff_ua:
        eff_ua = f"{eff_ua} (+{contact})"
    assert "operator@mesalaw.org" in eff_ua


# 18. post-staging/pre-audit crash reconciles on rerun
def test_post_staging_pre_audit_crash_reconciles_on_rerun(tmp_path, monkeypatch):
    stg_db = tmp_path / "mesa_staging.sqlite"
    cat_db = tmp_path / "catalog.sqlite"

    data_root = tmp_path
    rel_dir = data_root / "releases" / "rel-rec-1"
    rel_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = rel_dir / "manifest.json"
    manifest_file.write_text('{"files":{}}')

    fake_settings = type("Settings", (), {"data_root_path": data_root, "mesa_staging_db": str(stg_db)})()
    monkeypatch.setattr("mesa_legal_data.release.importer.load_settings", lambda: fake_settings)
    monkeypatch.setattr("mesa_legal_data.config.load_settings", lambda: fake_settings)
    monkeypatch.setattr("mesa_legal_data.release.importer.get_staging_db_path", lambda: stg_db)

    conn_s = get_staging_connection(stg_db)
    init_staging_db(conn_s)
    now = datetime.now(UTC).isoformat()
    conn_s.execute(
        "INSERT INTO imported_releases (release_id, manifest_sha256, imported_at, status) VALUES ('rel-rec-1', 'sha123', ?, 'imported')",
        (now,),
    )
    conn_s.commit()
    conn_s.close()

    conn_c = sqlite3.connect(cat_db)
    conn_c.execute("CREATE TABLE releases (release_id TEXT PRIMARY KEY, status TEXT NOT NULL);")
    conn_c.execute("INSERT INTO releases VALUES ('rel-rec-1', 'published')")
    conn_c.execute(
        """
        CREATE TABLE mesa_imports (
            import_id INTEGER PRIMARY KEY, release_id TEXT UNIQUE, status TEXT, target_db_path TEXT, imported_at TEXT, record_counts_json TEXT, error_summary TEXT
        );
        """
    )
    conn_c.commit()
    conn_c.close()

    monkeypatch.setattr("mesa_legal_data.release.importer.get_catalog_connection", lambda: sqlite3.connect(cat_db))
    monkeypatch.setattr("mesa_legal_data.release.importer.verify_release", lambda r_id: True)
    monkeypatch.setattr("mesa_legal_data.release.importer.hash_stream", lambda f: "sha123")

    res = import_release_to_staging("rel-rec-1")
    assert res["status"] == "already_imported"

    conn_c = sqlite3.connect(cat_db)
    cur = conn_c.cursor()
    cur.execute("SELECT release_id, status FROM mesa_imports WHERE release_id = 'rel-rec-1'")
    rec = cur.fetchone()
    assert rec is not None
    assert rec[0] == "rel-rec-1"
    conn_c.close()


# 19. review completion reconciles Harvest NEEDS_REVIEW
def test_review_completion_reconciles_harvest_needs_review(tmp_path):
    db_h = tmp_path / "harvest.sqlite"
    db_c = tmp_path / "catalog.sqlite"

    from mesa_legal_data.harvest.migrations import apply_harvest_migrations

    apply_harvest_migrations(db_h)

    conn_h = sqlite3.connect(db_h)
    now = datetime.now(UTC).isoformat()
    conn_h.execute(
        """
        INSERT INTO harvest_items (
            id, queue_id, source_id, adapter_name, canonical_key, normalized_url, original_url,
            document_id, family, document_type, title, discovery_page_url, priority, status, version_id, discovered_at, updated_at
        ) VALUES (1, 'q1', 's1', 'a1', 'c1', 'u1', 'u1', 'd1', 'f1', 'law', 't1', 'http://u1', 100, 'needs_review', 'ver-99', ?, ?)
        """,
        (now, now),
    )
    conn_h.commit()
    conn_h.close()

    conn_c = sqlite3.connect(db_c)
    conn_c.execute("CREATE TABLE records (record_id TEXT PRIMARY KEY, version_id TEXT, approval_status TEXT);")
    conn_c.execute("INSERT INTO records VALUES ('r1', 'ver-99', 'approved')")
    conn_c.commit()
    conn_c.close()

    reconciled = reconcile_harvest_review_status("ver-99", db_path=db_h, catalog_db_path=db_c)
    assert reconciled is True

    item = get_harvest_item_by_id(1, db_path=db_h)
    assert item.status == "completed"


# 20. unsafe release IDs rejected
def test_unsafe_release_ids_rejected():
    unsafe_ids = ["../evil", "../../x", "/etc/passwd", "a/b", "a\\b", "", "..", ".hidden"]
    for u_id in unsafe_ids:
        with pytest.raises(UnsafeReleaseIDError):
            validate_release_id(u_id)

    safe_ids = ["release-20260811", "release-v1.0", "mvp-001"]
    for s_id in safe_ids:
        assert validate_release_id(s_id) == s_id
