import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    BlockingValidationIssueExists,
    approve_version_streaming,
    get_connection,
    get_db_path,
    get_document,
    get_record,
    get_version,
    insert_artifact,
    migrate,
    open_issue,
    reject_version,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.web.app import create_app


def _setup_multi_record_version(tmp_path, doc_num="100"):
    db_path = get_db_path()
    migrate(None, db_path)

    doc_id = f"tr:legislation:law:{doc_num}"
    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / f"law{doc_num}" / "hash1"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    html = f"""<html>
<head><meta charset="utf-8"></head>
<body>
<h1>DENEME KANUNU {doc_num}</h1>
<p><b>Madde 1-</b> İlk madde metni 4721 sayılı Kanun uyarınca düzenlenmiştir.</p>
<p><b>Madde 2-</b> İkinci madde metni 5237 sayılı Kanun gereğince uygulanır.</p>
<p><b>Madde 3-</b> Üçüncü madde yürürlük maddesidir.</p>
</body>
</html>"""
    raw_bytes = html.encode("utf-8")
    raw_file.write_bytes(raw_bytes)

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)

    conn = get_connection()
    upsert_source(conn, "mevzuat", "Mevzuat", "T.C. Cumhurbaşkanlığı", "https://www.mevzuat.gov.tr")
    upsert_document(conn, doc_id, "legislation", "law", "TR", f"Deneme Kanunu {doc_num}", doc_num, "fetched")
    insert_artifact(
        conn,
        artifact_id=f"art-bulk-{doc_num}",
        document_id=doc_id,
        source_id="mevzuat",
        source_url=f"https://www.mevzuat.gov.tr/{doc_num}",
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
        metadata_json="{}",
    )
    conn.close()

    status = process_artifact_pipeline(artifact_id=f"art-bulk-{doc_num}")
    assert status == "needs_review"

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions WHERE document_id = ?", (doc_id,))
    ver_id = c.fetchone()[0]

    c.execute("SELECT record_id, record_type FROM records WHERE version_id = ?", (ver_id,))
    records = c.fetchall()
    conn.close()

    return doc_id, ver_id, records


def test_bulk_approve_success_all_records_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id, ver_id, records = _setup_multi_record_version(tmp_path, "101")

    # Ensure we have 1 legislation, 3 articles, and citations
    rec_types = [r[1] for r in records]
    assert "legislation" in rec_types
    assert rec_types.count("article") == 3
    assert "citation" in rec_types

    conn = get_connection()
    res = approve_version_streaming(conn, version_id=ver_id, reviewer="lead_reviewer", note="Toplu onay")
    assert res["status"] == "approved"
    assert res["approved_records"] == len(records)

    # Check version status
    ver = get_version(conn, ver_id)
    assert ver["approval_status"] == "approved"

    # Check document status
    doc = get_document(conn, doc_id)
    assert doc["lifecycle_status"] == "approved"

    # Check all records status & review trail
    for r_id, _ in records:
        rec = get_record(conn, r_id)
        assert rec["approval_status"] == "approved"

    c = conn.cursor()
    c.execute("SELECT count(*) FROM record_reviews WHERE reviewer = 'lead_reviewer' AND decision = 'approved'")
    assert c.fetchone()[0] == len(records)

    c.execute("SELECT action, subject_type, subject_id, actor FROM audit_events WHERE action = 'version_approve'")
    audit_row = c.fetchone()
    assert audit_row is not None
    assert audit_row[1] == "version"
    assert audit_row[2] == ver_id
    assert audit_row[3] == "lead_reviewer"
    conn.close()


def test_bulk_approve_fail_closed_on_child_record_blocker(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id, ver_id, records = _setup_multi_record_version(tmp_path, "102")

    article_record_id = [r[0] for r in records if r[1] == "article"][0]

    # Open a blocker issue on one child record
    conn = get_connection()
    open_issue(
        conn,
        issue_id="iss-blk-child-1",
        subject_type="record",
        subject_id=article_record_id,
        severity="blocker",
        code="CONTENT_VALIDATION_ERROR",
        message="Maddede kritik hukuki format hatasi",
        details_json="{}",
    )

    # Attempting to bulk approve must FAIL-CLOSED
    with pytest.raises(BlockingValidationIssueExists):
        approve_version_streaming(conn, version_id=ver_id, reviewer="lead_reviewer", note="Toplu onay denemesi")

    # Verify atomicity: no records approved
    for r_id, _ in records:
        rec = get_record(conn, r_id)
        assert rec["approval_status"] == "pending"

    ver = get_version(conn, ver_id)
    assert ver["approval_status"] == "pending"
    conn.close()


def test_bulk_reject_success_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id, ver_id, records = _setup_multi_record_version(tmp_path, "103")

    conn = get_connection()
    res = reject_version(conn, version_id=ver_id, reviewer="auditor", note="Yetersiz kaynak kalitesi")
    assert res["status"] == "rejected"
    assert res["rejected_records"] == len(records)

    # Check version & document status
    ver = get_version(conn, ver_id)
    assert ver["approval_status"] == "rejected"

    doc = get_document(conn, doc_id)
    assert doc["lifecycle_status"] == "rejected"

    # Check all records
    for r_id, _ in records:
        rec = get_record(conn, r_id)
        assert rec["approval_status"] == "rejected"

    c = conn.cursor()
    c.execute("SELECT count(*) FROM record_reviews WHERE reviewer = 'auditor' AND decision = 'rejected'")
    assert c.fetchone()[0] == len(records)

    c.execute("SELECT action, subject_type, subject_id, actor FROM audit_events WHERE action = 'version_reject'")
    audit_row = c.fetchone()
    assert audit_row is not None
    assert audit_row[1] == "version"
    assert audit_row[2] == ver_id
    assert audit_row[3] == "auditor"
    conn.close()


def test_bulk_review_web_api_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id, ver_id, records = _setup_multi_record_version(tmp_path, "104")

    app = create_app()
    client = TestClient(app)

    # 1. Test POST /api/versions/{version_id}/reject
    res_rej = client.post(
        f"/api/versions/{ver_id}/reject",
        json={"reviewer": "web_admin", "note": "Gecersiz surum"},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_rej.status_code == 200
    assert res_rej.json()["data"]["status"] == "rejected"
    assert res_rej.json()["data"]["rejected_records"] == len(records)

    # 2. Test POST /api/versions/{version_id}/approve on another version
    doc_id_2, ver_id_2, records_2 = _setup_multi_record_version(tmp_path, "105")
    res_app = client.post(
        f"/api/versions/{ver_id_2}/approve",
        json={"reviewer": "web_admin", "note": "Onaylandi"},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_app.status_code == 200
    assert res_app.json()["data"]["status"] == "approved"
    assert res_app.json()["data"]["approved_records"] == len(records_2)

    # 3. Test POST /api/versions/{version_id}/approve with child blocker -> 400
    doc_id_3, ver_id_3, records_3 = _setup_multi_record_version(tmp_path, "106")
    child_art_id = [r[0] for r in records_3 if r[1] == "article"][0]

    conn = get_connection()
    open_issue(
        conn,
        issue_id="iss-blk-api-1",
        subject_type="record",
        subject_id=child_art_id,
        severity="blocker",
        code="CONTENT_ERROR",
        message="Kritik engel",
        details_json="{}",
    )
    conn.close()

    res_blk = client.post(
        f"/api/versions/{ver_id_3}/approve",
        json={"reviewer": "web_admin", "note": "Onay denemesi"},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_blk.status_code == 400
    assert "VERSION_APPROVE_FAILED" in res_blk.text
