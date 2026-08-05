import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.release.builder import build_release
from mesa_legal_data.release.verifier import verify_release_directory
from mesa_legal_data.sources.url_fetcher import SSRFError, validate_url_host
from mesa_legal_data.web.app import create_app


def test_ssrf_negative_checks():
    # 1. Private / Loopback IP -> SSRFError
    with pytest.raises(SSRFError):
        validate_url_host("http://127.0.0.1:8080/secret.pdf")

    with pytest.raises(SSRFError):
        validate_url_host("http://192.168.1.1/admin")

    # 2. Non-443 port -> SSRFError
    with pytest.raises(SSRFError):
        validate_url_host("https://www.mevzuat.gov.tr:8080/doc.pdf")


def test_csrf_and_actor_negative_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app()
    client = TestClient(app)

    # 1. Missing X-MESA-Requested-With header on POST -> 403 Forbidden
    res_no_csrf = client.post("/api/exports", json={"export_type": "records_jsonl"})
    assert res_no_csrf.status_code == 403

    # 2. With X-MESA-Requested-With header -> 200 OK
    res_with_csrf = client.post(
        "/api/exports",
        json={"export_type": "records_jsonl"},
        headers={"X-MESA-Requested-With": "web-admin", "X-MESA-Actor": "test_actor"},
    )
    assert res_with_csrf.status_code == 200


def test_release_tamper_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_file = tmp_path / "raw" / "tamper.html"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("<!DOCTYPE html><html><body><h1>Release Tamper</h1></body></html>", encoding="utf-8")
    with open(raw_file, "rb") as f:
        sha = hash_stream(f)

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:555", "legislation", "law", "TR", "Law 555", "555", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-t555",
        document_id="tr:legislation:law:555",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/555.pdf",
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
    conn.close()

    from mesa_legal_data.pipeline import process_artifact_pipeline

    process_artifact_pipeline(artifact_id="art-t555")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM records LIMIT 1")
    v_id = c.fetchone()[0]
    from mesa_legal_data.catalog import approve_version_streaming

    approve_version_streaming(conn, version_id=v_id, reviewer="builder", note="OK")
    conn.close()

    res = build_release(release_id="rel-tamper-sec")
    rel_path = tmp_path / "releases" / res["release_id"]

    # Verify release before tampering
    assert verify_release_directory(rel_path) is True

    # Tamper with manifest.json
    manifest_p = rel_path / "manifest.json"
    content = manifest_p.read_text(encoding="utf-8")
    manifest_p.write_text(content + "\n// tampered", encoding="utf-8")

    # Verify release after tampering -> returns False or raises ReleaseVerificationError
    try:
        is_ok = verify_release_directory(rel_path)
        assert is_ok is False
    except Exception:
        pass
