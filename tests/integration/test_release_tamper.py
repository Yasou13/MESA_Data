import pytest

from mesa_legal_data.catalog import (
    approve_version_with_checks,
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release
from mesa_legal_data.release.verifier import ReleaseVerificationError, verify_release


def test_release_tamper_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hasht"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    text = "<!DOCTYPE html><html><body>\n<h1>TÜRK MEDENİ KANUNU</h1>\n<p><b>Madde 1-</b> Kanun uygulanır.</p>\n</body></html>"
    raw_file.write_text(text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = get_connection()
    upsert_document(
        conn,
        "tr:legislation:law:4721",
        "legislation",
        "law",
        "TR",
        "TMK",
        "4721",
        "fetched",
    )
    insert_artifact(
        conn,
        artifact_id="art-t-1",
        document_id="tr:legislation:law:4721",
        source_id="mevzuat",
        source_url="http://mevzuat.gov.tr/4721",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=byte_size,
        sha256=sha256,
        raw_path=str(raw_file.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    process_artifact_pipeline(artifact_id="art-t-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]

    approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Approved")
    conn.close()

    rel_id = "rel-tamper-1"
    build_release(release_id=rel_id)

    # 1. Untampered verify passes
    assert verify_release(rel_id) is True

    # 2. Tamper data file -> verify MUST fail!
    leg_jsonl = tmp_path / "releases" / rel_id / "data" / "legislation.jsonl"
    leg_jsonl.write_text(leg_jsonl.read_text(encoding="utf-8") + "\n//tampered\n")

    with pytest.raises(ReleaseVerificationError):
        verify_release(rel_id)
