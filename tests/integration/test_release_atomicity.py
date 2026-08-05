import pytest

from mesa_legal_data.audit import run_doctor_check
from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release


def test_release_state_machine_and_doctor(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_file = tmp_path / "raw" / "test.html"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("<!DOCTYPE html><html><body><h1>Kanun 1</h1><p><b>Madde 1-</b> Kanun metni.</p></body></html>", encoding="utf-8")
    with open(raw_file, "rb") as f:
        sha = hash_stream(f)

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:100", "legislation", "law", "TR", "Law 100", "100", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-atom-1",
        document_id="tr:legislation:law:100",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/law100.pdf",
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

    process_artifact_pipeline(artifact_id="art-atom-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT version_id FROM records")
    ver_id = c.fetchone()[0]
    approve_version_streaming(conn, version_id=ver_id, reviewer="atom_user", note="Approved")
    conn.close()

    rel_meta = build_release(release_id="rel-atom-01")
    assert rel_meta["status"] == "verified"

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT status FROM releases WHERE release_id = ?", ("rel-atom-01",))
    db_status = c.fetchone()[0]
    conn.close()
    assert db_status == "verified"

    doc = run_doctor_check()
    assert doc["data_root_writable"] is True
    assert doc["catalog_sqlite_healthy"] is True
