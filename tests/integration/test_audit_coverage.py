from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    insert_artifact,
    log_audit_event,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.web.app import create_app


def test_audit_event_recording_and_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_file = tmp_path / "raw" / "audit_test.html"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(
        "<!DOCTYPE html><html><body><h1>Kanun</h1><p><b>Madde 1-</b> m.</p></body></html>", encoding="utf-8"
    )
    with open(raw_file, "rb") as f:
        sha = hash_stream(f)

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:500", "legislation", "law", "TR", "Law 500", "500", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-audit-1",
        document_id="tr:legislation:law:500",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/500.pdf",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_file.stat().st_size,
        sha256=sha,
        raw_path=str(raw_file.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )

    # 1. Direct log_audit_event check
    log_audit_event(
        conn,
        actor="test_actor",
        action="manual_test",
        subject_type="test",
        subject_id="sub-1",
        reason="Testing audit coverage",
    )
    conn.close()

    process_artifact_pipeline(artifact_id="art-audit-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT version_id FROM records")
    v_id = c.fetchone()[0]

    # 2. Version approval audit event
    approve_version_streaming(conn, version_id=v_id, reviewer="auditor_user", note="Approved for audit")

    c.execute("SELECT action, actor FROM audit_events ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()

    actions = [r[0] for r in rows]
    actors = [r[1] for r in rows]

    assert "manual_test" in actions
    assert "version_approve" in actions
    assert "auditor_user" in actors

    # 3. Test HTTP download produces audit event
    app = create_app()
    client = TestClient(app)
    res = client.get("/api/artifacts/art-audit-1/download", headers={"X-MESA-Actor": "download_actor"})
    assert res.status_code == 200

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT action, actor FROM audit_events WHERE action = 'download_artifact'")
    down_audit = c.fetchone()
    conn.close()

    assert down_audit is not None
    assert down_audit[1] == "download_actor"
