import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    approve_record_with_checks,
    approve_version_streaming,
    get_artifact,
    get_connection,
    get_db_path,
    get_document,
    get_record,
    get_version_for_artifact,
    insert_artifact,
    migrate,
    open_issue,
    recompute_document_current_version,
    reject_record_with_checks,
    reject_version,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.harvest.queue import _check_canonical_committed
from mesa_legal_data.harvest.service_bridge import run_pipeline_item
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.publisher.client import MesaClientError
from mesa_legal_data.publisher.engine import build_delivery_plan, execute_publish_delivery
from mesa_legal_data.publisher.ledger import upsert_mesa_target_settings
from mesa_legal_data.publisher.models import DeliveryStatus, MesaTargetSettings
from mesa_legal_data.release import publish_release
from mesa_legal_data.release.builder import build_release
from mesa_legal_data.release.importer import (
    ReleaseNotPublished,
    import_release_to_staging,
)
from mesa_legal_data.release.verifier import verify_release
from mesa_legal_data.web.app import create_app

WEB_HEADERS = {"X-MESA-Requested-With": "web-admin"}


def _helper_create_law_artifact(
    tmp_path: Path,
    doc_id: str,
    raw_html: str,
    artifact_id: str,
    source_id: str = "mevzuat",
    pub_date: str | None = None,
    source_role: str | None = None,
) -> str:

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / source_id / "2026" / artifact_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"
    raw_bytes = raw_html.encode("utf-8")
    raw_file.write_bytes(raw_bytes)

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)

    meta_dict: dict[str, Any] = {}
    if pub_date:
        meta_dict["publication_date"] = pub_date
    if source_role:
        meta_dict["source_role"] = source_role

    conn = get_connection()
    upsert_source(conn, source_id, source_id.capitalize(), "Test Agency", f"https://example.com/{source_id}")
    upsert_document(conn, doc_id, "legislation", "law", "TR", f"Test Law {doc_id}", doc_id, "fetched")
    insert_artifact(
        conn,
        artifact_id=artifact_id,
        document_id=doc_id,
        source_id=source_id,
        source_url=f"https://example.com/{artifact_id}",
        retrieved_at="2026-08-01T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=len(raw_bytes),
        sha256=sha256,
        raw_path=str(raw_file.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json=json.dumps(meta_dict) if meta_dict else "{}",
    )
    conn.close()
    return artifact_id


def test_final_panel_confirmation_binds_exact_release_manifest_and_target(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:panel-frozen-final"
    art_v1 = _helper_create_law_artifact(
        tmp_path,
        doc_id,
        "<html><body><h1>Panel V1</h1><p><b>Madde 1-</b> Frozen.</p></body></html>",
        "art-panel-final-v1",
        pub_date="2026-01-01",
    )
    process_artifact_pipeline(art_v1)
    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    assert v1 is not None
    approve_version_streaming(conn, version_id=v1["version_id"], reviewer="auditor")
    conn.close()

    client = TestClient(create_app())
    prepared_response = client.post("/api/publisher/prepare?target_key=default", headers=WEB_HEADERS)
    assert prepared_response.status_code == 200
    prepared = prepared_response.json()["data"]
    assert prepared["release_id"]
    assert len(prepared["manifest_sha256"]) == 64
    assert len(prepared["target_config_sha256"]) == 64

    # Live catalog changes after the confirmation summary was created.
    art_v2 = _helper_create_law_artifact(
        tmp_path,
        doc_id,
        "<html><body><h1>Panel V2</h1><p><b>Madde 1-</b> Live changed.</p></body></html>",
        "art-panel-final-v2",
        pub_date="2026-02-01",
    )
    process_artifact_pipeline(art_v2)
    conn = get_connection()
    v2 = get_version_for_artifact(conn, art_v2)
    assert v2 is not None
    approve_version_streaming(conn, version_id=v2["version_id"], reviewer="auditor")
    conn.close()

    bad_response = client.post(
        "/api/publisher/publish",
        headers=WEB_HEADERS,
        json={
            "target_key": prepared["target_key"],
            "release_id": prepared["release_id"],
            "manifest_sha256": "0" * 64,
            "target_config_sha256": prepared["target_config_sha256"],
        },
    )
    assert bad_response.status_code == 409

    captured: dict[str, Any] = {}

    def fake_submit(conn, *, operation_type, requested_by, input_dict):
        captured.update(input_dict)
        return "op-frozen-final"

    monkeypatch.setattr("mesa_legal_data.operations.submit_operation", fake_submit)
    monkeypatch.setattr(
        "mesa_legal_data.publisher.client.MesaClient.run_preflight_checks",
        lambda self, **kwargs: type("Report", (), {"overall_status": "PASS", "checks": []})(),
    )
    response = client.post(
        "/api/publisher/publish",
        headers=WEB_HEADERS,
        json={
            "target_key": prepared["target_key"],
            "release_id": prepared["release_id"],
            "manifest_sha256": prepared["manifest_sha256"],
            "target_config_sha256": prepared["target_config_sha256"],
        },
    )
    assert response.status_code == 200
    assert captured["release_id"] == prepared["release_id"]
    frozen_chunks, _ = build_delivery_plan(release_id=captured["release_id"])
    assert {chunk.version_id for chunk, _ in frozen_chunks} == {v1["version_id"]}


def test_master_a_chronology_current_version_selection(tmp_path, monkeypatch):
    """Test A: Legal Chronology Current Version Selection - Historical backfill never replaces newer current version."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:chronology-1"

    # Step 1: Process 2026 current version
    html_2026 = """<html><body><h1>CHRONOLOGY LAW</h1><p><b>Madde 1-</b> 2026 version text.</p></body></html>"""
    art_2026 = _helper_create_law_artifact(tmp_path, doc_id, html_2026, "art-2026", pub_date="2026-06-01")
    st_2026 = process_artifact_pipeline(art_2026)
    assert st_2026 in ("needs_review", "approved")

    conn = get_connection()
    doc = get_document(conn, doc_id)
    assert doc is not None
    v_2026 = get_version_for_artifact(conn, art_2026)
    assert v_2026 is not None
    v_2026_id = v_2026["version_id"]
    assert doc["current_version_id"] == v_2026_id
    assert "2026-06-01" in v_2026_id
    conn.close()

    # Step 2: Ingest older 2010 historical backfill
    html_2010 = """<html><body><h1>CHRONOLOGY LAW OLD</h1><p><b>Madde 1-</b> 2010 version text.</p></body></html>"""
    art_2010 = _helper_create_law_artifact(tmp_path, doc_id, html_2010, "art-2010", pub_date="2010-01-01")
    st_2010 = process_artifact_pipeline(art_2010)
    assert st_2010 in ("needs_review", "approved")

    # Verify current_version_id remains 2026 version
    conn = get_connection()
    doc_after = get_document(conn, doc_id)
    assert doc_after is not None
    assert doc_after["current_version_id"] == v_2026_id

    # Recomputing explicitly also preserves the newer version
    chosen = recompute_document_current_version(conn, doc_id)
    assert chosen == v_2026_id
    conn.close()


def test_master_b_historical_version_approval_lifecycle_invariant(tmp_path, monkeypatch):
    """Test B: Historical Version Approval/Rejection Invariant - Historical version approval does not alter document lifecycle or current version."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:hist-review-1"

    # Current version 2026
    html_2026 = """<html><body><h1>HIST REVIEW LAW 2026</h1><p><b>Madde 1-</b> 2026 text.</p></body></html>"""
    art_2026 = _helper_create_law_artifact(tmp_path, doc_id, html_2026, "art-2026-b", pub_date="2026-06-01")
    process_artifact_pipeline(art_2026)

    # Historical version 2010
    html_2010 = """<html><body><h1>HIST REVIEW LAW 2010</h1><p><b>Madde 1-</b> 2010 text.</p></body></html>"""
    art_2010 = _helper_create_law_artifact(tmp_path, doc_id, html_2010, "art-2010-b", pub_date="2010-01-01")
    process_artifact_pipeline(art_2010)

    conn = get_connection()
    v_2010 = get_version_for_artifact(conn, art_2010)
    v_2026 = get_version_for_artifact(conn, art_2026)
    assert v_2010 is not None
    assert v_2026 is not None

    # Current document lifecycle is needs_review
    doc = get_document(conn, doc_id)
    assert doc["lifecycle_status"] == "needs_review"
    assert doc["current_version_id"] == v_2026["version_id"]

    # Reject the historical 2010 version
    reject_version(conn, version_id=v_2010["version_id"], reviewer="test_auditor", note="Old historical rejected")

    # Check doc lifecycle is STILL needs_review (not rejected!)
    doc_after_hist_rej = get_document(conn, doc_id)
    assert doc_after_hist_rej["lifecycle_status"] == "needs_review"
    assert doc_after_hist_rej["current_version_id"] == v_2026["version_id"]

    # Approve the 2010 historical version
    approve_version_streaming(conn, version_id=v_2010["version_id"], reviewer="test_auditor")
    doc_after_hist_app = get_document(conn, doc_id)
    assert doc_after_hist_app["lifecycle_status"] == "needs_review"
    assert doc_after_hist_app["current_version_id"] == v_2026["version_id"]

    # Now approve the current 2026 version
    approve_version_streaming(conn, version_id=v_2026["version_id"], reviewer="test_auditor")
    doc_final = get_document(conn, doc_id)
    assert doc_final["lifecycle_status"] == "approved"
    assert doc_final["current_version_id"] == v_2026["version_id"]
    conn.close()


def test_master_c_pipeline_item_artifact_version_mapping(tmp_path, monkeypatch):
    """Test C: Pipeline Item Artifact-to-Version Mapping - Service bridge maps artifact to its produced version."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:art-map-1"

    # Ingest 2026 version first
    html_2026 = """<html><body><h1>MAP LAW 2026</h1><p><b>Madde 1-</b> 2026 text.</p></body></html>"""
    art_2026 = _helper_create_law_artifact(tmp_path, doc_id, html_2026, "art-map-2026", pub_date="2026-06-01")
    process_artifact_pipeline(art_2026)

    # Ingest 2010 version via run_pipeline_item
    html_2010 = """<html><body><h1>MAP LAW 2010</h1><p><b>Madde 1-</b> 2010 text.</p></body></html>"""
    art_2010 = _helper_create_law_artifact(tmp_path, doc_id, html_2010, "art-map-2010", pub_date="2010-01-01")
    res = run_pipeline_item(art_2010)

    conn = get_connection()
    v_2010 = get_version_for_artifact(conn, art_2010)
    assert v_2010 is not None
    assert res.version_id == v_2010["version_id"]
    assert "2010-01-01" in res.version_id

    # Queue recovery also returns version_id matching artifact
    committed, app_st, rec_v_id = _check_canonical_committed(art_2010)
    assert committed is True
    assert rec_v_id == v_2010["version_id"]
    conn.close()


def test_master_d_instance_scoped_record_reviews(tmp_path, monkeypatch):
    """Test D: Instance-Scoped Review Records - Shared logical record IDs across versions are reviewed independently."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:shared-rec-1"

    # Both versions have identical Madde 1 text and hash, but distinct HTML wrappers
    html_v1 = """<html><body><h1>SHARED LAW V1</h1><!-- v1 wrapper --><p><b>Madde 1-</b> Aynen korunan madde metni.</p></body></html>"""
    html_v2 = """<html><body><h1>SHARED LAW V2</h1><!-- v2 wrapper --><p><b>Madde 1-</b> Aynen korunan madde metni.</p></body></html>"""
    art_v1 = _helper_create_law_artifact(tmp_path, doc_id, html_v1, "art-v1-inst", pub_date="2020-01-01")
    art_v2 = _helper_create_law_artifact(tmp_path, doc_id, html_v2, "art-v2-inst", pub_date="2025-01-01")

    process_artifact_pipeline(art_v1)
    process_artifact_pipeline(art_v2)

    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    v2 = get_version_for_artifact(conn, art_v2)
    assert v1 is not None and v2 is not None

    rec_id = f"{doc_id}:article:1"
    r1 = get_record(conn, rec_id, version_id=v1["version_id"])
    r2 = get_record(conn, rec_id, version_id=v2["version_id"])
    assert r1 is not None and r2 is not None
    assert r1["record_instance_id"] != r2["record_instance_id"]

    # Approve r1 in v1
    approve_record_with_checks(
        conn,
        record_id=rec_id,
        reviewer="auditor1",
        version_id=v1["version_id"],
        record_instance_id=r1["record_instance_id"],
    )

    # Verify r1 is approved, but r2 in v2 is STILL pending
    r1_after = get_record(conn, rec_id, version_id=v1["version_id"])
    r2_after = get_record(conn, rec_id, version_id=v2["version_id"])
    assert r1_after["approval_status"] == "approved"
    assert r2_after["approval_status"] == "pending"

    # Reject r2 in v2
    reject_record_with_checks(
        conn,
        record_id=rec_id,
        reviewer="auditor2",
        version_id=v2["version_id"],
        record_instance_id=r2["record_instance_id"],
    )
    r1_final = get_record(conn, rec_id, version_id=v1["version_id"])
    r2_final = get_record(conn, rec_id, version_id=v2["version_id"])
    assert r1_final["approval_status"] == "approved"
    assert r2_final["approval_status"] == "rejected"
    conn.close()


def test_master_e_non_null_and_unique_review_ids(tmp_path, monkeypatch):
    """Test E: Non-null and Unique Review IDs in record_reviews table."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:unique-rev-1"
    html = """<html><body><h1>MULTI REC LAW</h1>
    <p><b>Madde 1-</b> Metin 1.</p>
    <p><b>Madde 2-</b> Metin 2.</p>
    <p><b>Madde 3-</b> Metin 3.</p>
    </body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-unique-rev", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None

    # Bulk streaming approval
    approve_version_streaming(conn, version_id=ver["version_id"], reviewer="lead_auditor")

    cur = conn.cursor()
    cur.execute(
        "SELECT review_id, record_instance_id, version_id FROM record_reviews WHERE version_id = ?",
        (ver["version_id"],),
    )
    rows = cur.fetchall()
    assert len(rows) >= 3

    review_ids = [r[0] for r in rows]
    # Check all review_ids are non-null and strictly unique
    assert all(rid is not None and len(rid) > 0 for rid in review_ids)
    assert len(review_ids) == len(set(review_ids))
    conn.close()


def test_master_f_missing_publication_date_on_original_publication(tmp_path, monkeypatch):
    """Test F: Missing Publication Date on Original Publication triggers REVIEW and issue."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:no-date-rg"
    html = """<html><body><h1>RESMI GAZETE KANUN</h1><p><b>Madde 1-</b> Resmi Gazete yayımı metni.</p></body></html>"""
    art_id = _helper_create_law_artifact(
        tmp_path,
        doc_id,
        html,
        "art-no-date-rg",
        source_id="resmi_gazete",
        pub_date=None,
        source_role="original_publication",
    )
    st = process_artifact_pipeline(art_id)
    assert st == "needs_review"

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    assert ver["approval_status"] == "pending"
    assert ver["auto_approved"] is False

    cur = conn.cursor()
    cur.execute("SELECT code, severity FROM validation_issues WHERE version_id = ?", (ver["version_id"],))
    issues = cur.fetchall()
    assert any(i[0] == "PUBLICATION_DATE_MISSING" for i in issues)
    conn.close()


def test_master_g_crash_safe_canonical_generation_writes(tmp_path, monkeypatch):
    """Test G: Crash-Safe Canonical Writes - Corrupted or aborted transaction does not overwrite active canonical file."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:atomic-can-1"
    html_v1 = """<html><body><h1>ATOMIC LAW</h1><p><b>Madde 1-</b> İlk geçerli sürüm metni.</p></body></html>"""
    art_v1 = _helper_create_law_artifact(tmp_path, doc_id, html_v1, "art-atomic-v1", pub_date="2026-01-01")
    process_artifact_pipeline(art_v1)

    conn = get_connection()
    ver1 = get_version_for_artifact(conn, art_v1)
    assert ver1 is not None
    active_can_file = tmp_path / ver1["canonical_path"]
    assert active_can_file.exists()
    original_can_content = active_can_file.read_text(encoding="utf-8")
    conn.close()

    # If force reprocess fails halfway due to mock db lock or exception
    def mock_broken_insert(*args, **kwargs):
        raise sqlite3.OperationalError("Simulated mid-pipeline DB transaction crash")

    monkeypatch.setattr("mesa_legal_data.pipeline.insert_record", mock_broken_insert)
    with pytest.raises(sqlite3.OperationalError):
        process_artifact_pipeline(art_v1, force_reprocess=True)

    # Active canonical file content must remain completely unmodified
    assert active_can_file.read_text(encoding="utf-8") == original_can_content


def test_master_h_sixteen_hex_version_id_and_canonical_sha(tmp_path, monkeypatch):
    """Test H: Full Canonical Text Hash and 16-hex version ID hash."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:hash-len-1"
    html = """<html><body><h1>HASH LENGTH TEST</h1><p><b>Madde 1-</b> Madde 1 metni.</p></body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-hash-len", pub_date="2026-08-10")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    v_id = ver["version_id"]
    parts = v_id.split(":")
    # The last part is the 16-char artifact SHA prefix
    assert len(parts[-1]) == 16
    assert len(ver["canonical_sha256"]) == 64
    conn.close()


def test_master_i_candidate_scoped_release_blocker_checks(tmp_path, monkeypatch):
    """Test I: Candidate-Scoped Release Blocker Check - Unrelated document blocker does not prevent building a healthy release."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Doc 1: Healthy & Approved
    doc1 = "tr:legislation:law:healthy-1"
    html1 = """<html><body><h1>HEALTHY LAW</h1><p><b>Madde 1-</b> Sağlıklı madde metni.</p></body></html>"""
    art1 = _helper_create_law_artifact(tmp_path, doc1, html1, "art-healthy", pub_date="2026-01-01")
    process_artifact_pipeline(art1)

    conn = get_connection()
    v1 = get_version_for_artifact(conn, art1)
    assert v1 is not None
    approve_version_streaming(conn, version_id=v1["version_id"], reviewer="auditor")

    # Doc 2: Broken document with open blocker issue
    doc2 = "tr:legislation:law:broken-2"
    html2 = """<html><body><h1>BROKEN LAW</h1><p><b>Madde 1-</b> Bozuk madde.</p></body></html>"""
    art2 = _helper_create_law_artifact(tmp_path, doc2, html2, "art-broken", pub_date="2026-01-01")
    process_artifact_pipeline(art2)
    v2 = get_version_for_artifact(conn, art2)
    assert v2 is not None

    open_issue(
        conn,
        issue_id=f"iss-{uuid.uuid4().hex[:8]}",
        subject_type="version",
        subject_id=v2["version_id"],
        version_id=v2["version_id"],
        severity="blocker",
        code="TEST_BLOCKER",
        message="Critical blocking issue on Doc 2",
        details_json="{}",
    )
    conn.close()

    rel_id = f"rel-candidate-test-{uuid.uuid4().hex[:6]}"
    manifest = build_release(release_id=rel_id)
    assert manifest is not None
    assert manifest.get("release_id") == rel_id
    assert verify_release(rel_id) is True


@respx.mock
def test_master_j_release_bound_delivery_plan_and_cancellation(tmp_path, monkeypatch):
    """Test J & K: Release-Bound MESA Delivery Plan and Cancellation Callback."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "test_secret_api_key")
    monkeypatch.setenv("MESA_DATA_MESA_ALLOWED_HOST", "mock-mesa.internal")

    respx.get("https://mock-mesa.internal/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))

    doc_id = "tr:legislation:law:pub-rel-bound"
    html = """<html><body><h1>PUBLISH BOUND LAW</h1><p><b>Madde 1-</b> Yayınlanacak madde metni.</p></body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-pub-bound", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    # Configure verified mock target settings
    settings = MesaTargetSettings(
        target_key="default",
        base_url="https://mock-mesa.internal",
        tenant_id="default",
        workspace_id="legal",
        dataset_id="tr_legislation",
        agent_id="publisher",
        contract_source="configured",
        health_path="/health",
        session_start_path="/v4/sessions/start",
        publish_path="/v4/memory/insert",
        mutation_status_path_template="/v4/mutations/{mutation_id}",
    )
    upsert_mesa_target_settings(conn, settings)
    respx.post("https://mock-mesa.internal/v4/sessions/start").mock(
        return_value=httpx.Response(201, json={"status": "started", "session_id": "sess-cancel"})
    )

    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    approve_version_streaming(conn, version_id=ver["version_id"], reviewer="auditor")
    conn.close()

    rel_id = f"rel-pub-{uuid.uuid4().hex[:6]}"
    build_release(release_id=rel_id)

    # 1. Build delivery plan strictly from release_id
    chunks, summary = build_delivery_plan(release_id=rel_id)
    assert len(chunks) > 0
    assert summary.ready_documents >= 1

    # 2. Test cancellation callback enforcement
    cancelled_called = False

    def mock_is_cancelled():
        nonlocal cancelled_called
        cancelled_called = True
        return True

    del_res = execute_publish_delivery(
        delivery_id=f"del-canc-{uuid.uuid4().hex[:6]}",
        release_id=rel_id,
        is_cancelled_cb=mock_is_cancelled,
    )
    assert cancelled_called is True
    assert del_res.get("status") == DeliveryStatus.CANCELLED.value


def test_master_m_and_n_reprocess_endpoints(tmp_path, monkeypatch):
    """Test M & N: Document and Version Specific Reprocess Endpoints."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    client = TestClient(create_app())

    doc_id = "tr:legislation:law:reprocess-api-1"
    html = """<html><body><h1>API REPROCESS LAW</h1><p><b>Madde 1-</b> Reprocess test.</p></body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-reprocess-api", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    conn.close()

    # Document reprocess
    resp_doc = client.post(f"/api/documents/{doc_id}/reprocess", headers=WEB_HEADERS)
    assert resp_doc.status_code == 200
    assert resp_doc.json()["data"]["artifact_id"] == art_id

    # Version reprocess
    resp_ver = client.post(f"/api/versions/{ver['version_id']}/reprocess", headers=WEB_HEADERS)
    assert resp_ver.status_code == 200
    assert resp_ver.json()["data"]["version_id"] == ver["version_id"]


def test_master_o_upload_with_publication_date(tmp_path, monkeypatch):
    """Test O: Manual Upload with publication_date."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    client = TestClient(create_app())

    db_path = get_db_path()
    migrate(None, db_path)

    doc_id = "tr:legislation:law:manual-pubdate-1"
    html_bytes = b"<html><body><h1>MANUAL PUBDATE</h1><p><b>Madde 1-</b> Madde metni.</p></body></html>"

    resp = client.post(
        "/api/manual/upload-file",
        headers=WEB_HEADERS,
        data={
            "source_id": "resmi_gazete",
            "document_id": doc_id,
            "family": "legislation",
            "document_type": "law",
            "jurisdiction": "TR",
            "title": "Manual Pubdate Law",
            "publication_date": "2026-05-20",
        },
        files={"file": ("upload.html", html_bytes, "text/html")},
    )
    assert resp.status_code == 200
    art_id = resp.json()["data"]["artifact_id"]

    # Pipeline process should use the publication date
    st = process_artifact_pipeline(art_id)
    assert st in ("approved", "needs_review")

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    assert "2026-05-20" in ver["version_id"]
    conn.close()


def test_master_r_staging_import_invariants(tmp_path, monkeypatch):
    """Test R: Staging Import Semantics - Rejects unverified / unapproved / revoked releases."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    doc_id = "tr:legislation:law:stg-inv-1"
    html = """<html><body><h1>STG INV LAW</h1><p><b>Madde 1-</b> Madde metni.</p></body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-stg-inv", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    approve_version_streaming(conn, version_id=ver["version_id"], reviewer="auditor")
    conn.close()

    rel_id = f"rel-stg-inv-{uuid.uuid4().hex[:6]}"
    build_release(release_id=rel_id)

    # 1. Un-published release cannot be imported
    with pytest.raises(ReleaseNotPublished):
        import_release_to_staging(rel_id)

    # Publish release
    publish_release(rel_id)

    # 2. Import published release
    res = import_release_to_staging(rel_id)
    assert res.get("status") in ("imported", "already_imported")

    # 3. Re-importing same release is idempotent and reconciles audit
    res_dup = import_release_to_staging(rel_id)
    assert res_dup.get("status") == "already_imported"


def test_master_p_truthful_duplicate_evaluation(tmp_path, monkeypatch):
    """Test P: Truthful Duplicate Evaluation in Quality Gate."""
    from mesa_legal_data.quality import evaluate_quality

    report = evaluate_quality(
        raw_info={"byte_size": 100, "sha256": "a" * 64, "file_exists": True, "is_duplicate": True},
        source_info={"source_id": "mevzuat"},
        canonical_records=[
            {
                "id": "doc1",
                "title": "Title",
                "source": {"artifact_sha256": "a" * 64},
                "provenance": {"pipeline_run_id": "r1"},
            }
        ],
        canonical_text="Kanun metni Madde 1.",
        parser_name="test_parser",
        parser_version="1.0.0",
    )
    dup_checks = [c for c in report.checks if c.name == "duplicate_evaluation"]
    assert len(dup_checks) == 1
    assert dup_checks[0].status == "REVIEW"


def test_master_l_truthful_operations_job_statuses(tmp_path, monkeypatch):
    """Test L: Truthful Operation Job Statuses in operations.py."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    from mesa_legal_data.catalog import create_operation_job, get_operation_job, update_operation_job

    db_path = get_db_path()
    migrate(None, db_path)
    conn = get_connection()

    op_id = f"op-{uuid.uuid4().hex[:8]}"
    create_operation_job(
        conn,
        operation_id=op_id,
        operation_type="mesa_v4_delivery",
        requested_by="system",
        input_json=json.dumps({"test": True}),
    )

    for st in ("partial", "awaiting_external", "succeeded", "failed", "cancelled"):
        update_operation_job(conn, op_id, status=st)
        job = get_operation_job(conn, op_id)
        assert job is not None
        assert job["status"] == st

    conn.close()


def test_master_t_doctor_and_integrity_audit(tmp_path, monkeypatch):
    """Test T: Doctor and Integrity Audit Checks."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    from mesa_legal_data.audit import run_doctor_check, run_integrity_audit

    db_path = get_db_path()
    migrate(None, db_path)

    doc_res = run_doctor_check()
    assert doc_res.get("catalog_sqlite_healthy") is True
    assert doc_res.get("recovery_recommended") is False

    audit_res = run_integrity_audit()
    assert audit_res.get("corrupted", 0) == 0
    assert audit_res.get("missing", 0) == 0


def test_master_u_migration_0010_clean_application(tmp_path):
    """Test U: Migration 0010 Clean Application on fresh database."""
    db_file = tmp_path / "fresh_migration.sqlite"
    migrate(None, db_file)

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
    applied = [r[0] for r in cur.fetchall()]
    assert "0010_mvp_master_closure.sql" in applied

    # Verify tables and columns exist
    cur.execute("PRAGMA table_info(record_reviews)")
    cols = [r[1] for r in cur.fetchall()]
    assert "review_id" in cols
    assert "record_instance_id" in cols
    assert "version_id" in cols

    cur.execute("PRAGMA table_info(validation_issues)")
    v_cols = [r[1] for r in cur.fetchall()]
    assert "record_instance_id" in v_cols
    assert "version_id" in v_cols
    conn.close()


def test_master_w_privacy_blocker_prevents_auto_approval(tmp_path, monkeypatch):
    """Test W: Privacy Blocker Prevents Auto-Approval."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:privacy-block-1"
    # Contains a synthetic Turkish T.C. Kimlik No and phone number
    html = """<html><body><h1>PRIVACY LAW</h1><p><b>Madde 1-</b> Vatandaş 12345678901 ve tel: 05321234567 hakkında hükümler.</p></body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-privacy-block", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    # Auto-approval must not occur because privacy is flagged
    assert ver["approval_status"] == "pending"
    assert ver["auto_approved"] is False
    assert ver["privacy_status"] == "flagged"
    conn.close()


def test_master_af_target_settings_contract_truthful_status(tmp_path, monkeypatch):
    """Test AF: Target Settings Contract Truthful Status."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    from mesa_legal_data.publisher.ledger import get_mesa_target_settings, upsert_mesa_target_settings

    db_path = get_db_path()
    migrate(None, db_path)
    conn = get_connection()

    default_settings = get_mesa_target_settings(conn, "default")
    assert default_settings.contract_source == "unknown"

    cfg_settings = MesaTargetSettings(
        target_key="prod",
        base_url="https://mesa.prod.internal",
        contract_source="configured",
        health_path="/health",
        publish_path="/publish",
    )
    upsert_mesa_target_settings(conn, cfg_settings)

    retrieved = get_mesa_target_settings(conn, "prod")
    assert retrieved.contract_source == "configured"
    conn.close()


def test_final_release_plan_is_frozen_version_aware_and_revocation_guarded(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:frozen-final"
    article = "<p><b>Madde 9-</b> Aynı madde metni.</p>"

    art_v1 = _helper_create_law_artifact(
        tmp_path,
        doc_id,
        f"<html><body><h1>V1</h1>{article}</body></html>",
        "art-frozen-v1",
        pub_date="2026-01-01",
    )
    process_artifact_pipeline(art_v1)
    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    assert v1 is not None
    approve_version_streaming(conn, version_id=v1["version_id"], reviewer="auditor")
    conn.close()

    art_v2 = _helper_create_law_artifact(
        tmp_path,
        doc_id,
        f"<html><body><h1>V2 changed heading</h1>{article}</body></html>",
        "art-frozen-v2",
        pub_date="2026-02-01",
    )
    process_artifact_pipeline(art_v2)
    conn = get_connection()
    v2 = get_version_for_artifact(conn, art_v2)
    assert v2 is not None
    approve_version_streaming(conn, version_id=v2["version_id"], reviewer="auditor")

    # Reproduce the dangerous equality case: the same logical Article 9 and
    # hash are present in both versions. A record_id+hash join would leak v1.
    r2 = conn.execute(
        "SELECT canonical_path, canonical_line, record_sha256 FROM records WHERE version_id = ? AND record_type = 'article'",
        (v2["version_id"],),
    ).fetchone()
    assert r2 is not None
    conn.execute(
        """UPDATE records SET canonical_path = ?, canonical_line = ?, record_sha256 = ?
           WHERE version_id = ? AND record_type = 'article'""",
        (r2[0], r2[1], r2[2], v1["version_id"]),
    )
    conn.close()

    release_id = "rel-frozen-final"
    build_release(release_id=release_id)

    # Mutate the live catalog after the human-visible release was frozen.
    art_v3 = _helper_create_law_artifact(
        tmp_path,
        doc_id,
        "<html><body><h1>V3</h1><p><b>Madde 9-</b> Yeni canlı metin.</p></body></html>",
        "art-frozen-v3",
        pub_date="2026-03-01",
    )
    process_artifact_pipeline(art_v3)
    conn = get_connection()
    v3 = get_version_for_artifact(conn, art_v3)
    assert v3 is not None
    approve_version_streaming(conn, version_id=v3["version_id"], reviewer="auditor")
    conn.close()

    chunks, _ = build_delivery_plan(release_id=release_id)
    assert chunks
    assert {chunk.version_id for chunk, _ in chunks} == {v2["version_id"]}
    assert all("Yeni canlı metin" not in chunk.content for chunk, _ in chunks)

    conn = get_connection()
    conn.execute("UPDATE releases SET status = 'revoked' WHERE release_id = ?", (release_id,))
    conn.close()
    with pytest.raises(MesaClientError, match="lifecycle status revoked"):
        build_delivery_plan(release_id=release_id)


def test_final_invalid_calendar_dates_and_metadata_fill_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:calendar-final"
    html = "<html><body><h1>Date Law</h1><p><b>Madde 1-</b> Metin.</p></body></html>"

    art_invalid = _helper_create_law_artifact(
        tmp_path, doc_id, html, "art-invalid-date", source_id="resmi_gazete", pub_date="2026-02-31"
    )
    process_artifact_pipeline(art_invalid)
    conn = get_connection()
    invalid_version = get_version_for_artifact(conn, art_invalid)
    assert invalid_version is not None
    assert "unknown-date" in invalid_version["version_id"]
    assert invalid_version["approval_status"] == "pending"
    assert invalid_version["quality_status"] != "PASS"
    assert (
        conn.execute(
            "SELECT count(*) FROM validation_issues WHERE version_id = ? AND code = 'LEGAL_DATE_INVALID'",
            (invalid_version["version_id"],),
        ).fetchone()[0]
        == 1
    )
    conn.close()

    # Identical immutable bytes may gain a missing authoritative date, but an
    # existing value is never silently overwritten by a conflicting value.
    meta_doc = "tr:legislation:law:metadata-final"
    meta_html = "<html><body><h1>Metadata Law</h1><p><b>Madde 1-</b> Ayrı metin.</p></body></html>"
    first = _helper_create_law_artifact(tmp_path, meta_doc, meta_html, "art-meta-first")
    _helper_create_law_artifact(tmp_path, meta_doc, meta_html, "art-meta-second", pub_date="2026-08-10")
    conn = get_connection()
    stored = get_artifact(conn, first)
    assert stored is not None
    assert json.loads(stored["metadata_json"])["publication_date"] == "2026-08-10"
    conn.close()

    _helper_create_law_artifact(tmp_path, meta_doc, meta_html, "art-meta-third", pub_date="2026-08-11")
    conn = get_connection()
    stored = get_artifact(conn, first)
    assert stored is not None
    assert json.loads(stored["metadata_json"])["publication_date"] == "2026-08-10"
    assert (
        conn.execute(
            "SELECT count(*) FROM validation_issues WHERE subject_id = ? AND code = 'ARTIFACT_METADATA_CONFLICT'",
            (first,),
        ).fetchone()[0]
        == 1
    )
    conn.close()
