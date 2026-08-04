import sqlite3

from mesa_legal_data.catalog import (
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline


def test_pipeline_persistence_integration(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law6098" / "hash2"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    text = "<!DOCTYPE html><html><body><h1>TÜRK BORÇLAR KANUNU</h1><p><b>Madde 1-</b> Sözleşme, tarafların iradelerini karşılıklı ve birbirine uygun olarak açıklamalarıyla kurulur.</p></body></html>"
    raw_file.write_text(text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = sqlite3.connect(db_path)
    upsert_document(
        conn,
        "tr:legislation:law:6098",
        "legislation",
        "law",
        "TR",
        "Türk Borçlar Kanunu",
        "6098",
        "fetched",
    )
    insert_artifact(
        conn,
        artifact_id="art-6098",
        document_id="tr:legislation:law:6098",
        source_id="mevzuat",
        source_url="http://mevzuat.gov.tr/6098",
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

    status = process_artifact_pipeline(artifact_id="art-6098")
    assert status == "needs_review"

    # Verify canonical part file was written to disk
    canonical_files = list((tmp_path / "canonical").glob("**/*.jsonl"))
    assert len(canonical_files) >= 1
