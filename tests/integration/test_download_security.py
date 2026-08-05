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
from mesa_legal_data.web.app import create_app


def test_download_security_traversal_and_symlinks(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "valid.html"
    raw_file.write_text("<!DOCTYPE html><html><body>Valid</body></html>", encoding="utf-8")
    with open(raw_file, "rb") as f:
        valid_sha = hash_stream(f)

    # Symlink artifact file
    symlink_file = raw_dir / "symlink.html"
    try:
        symlink_file.symlink_to(raw_file)
    except OSError:
        pass

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:999", "legislation", "law", "TR", "Law 999", "999", "fetched")

    insert_artifact(
        conn,
        artifact_id="art-valid",
        document_id="tr:legislation:law:999",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/valid.html",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_file.stat().st_size,
        sha256=valid_sha,
        raw_path="raw/valid.html",
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )

    insert_artifact(
        conn,
        artifact_id="art-symlink",
        document_id="tr:legislation:law:999",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/symlink.html",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_file.stat().st_size,
        sha256="40b7a7b09d31744bf43ed974880e546bad540a079f347ea381050e2aa3db4afc",
        raw_path="raw/symlink.html",
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    app = create_app()
    client = TestClient(app)

    # 1. Non-existent artifact ID -> 404
    res_404 = client.get("/api/artifacts/art-nonexistent/download")
    assert res_404.status_code == 404

    # 2. Symlink download -> 403
    if symlink_file.exists():
        res_sym = client.get("/api/artifacts/art-symlink/download")
        assert res_sym.status_code == 403

    # 3. Valid download -> 200
    res_ok = client.get("/api/artifacts/art-valid/download")
    assert res_ok.status_code == 200
    assert res_ok.content == b"<!DOCTYPE html><html><body>Valid</body></html>"
