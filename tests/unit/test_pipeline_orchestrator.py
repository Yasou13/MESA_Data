import sqlite3

from mesa_legal_data.catalog import (
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline


def test_pipeline_orchestration(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    # 1. Prepare raw synthetic legislation file
    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hash1"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    text = "<!DOCTYPE html><html><body><h1>TÜRK MEDENİ KANUNU</h1><p><b>Madde 1-</b> Kanun, sözüyle ve özüyle değindiği bütün konularda uygulanır.</p><p><b>Madde 2-</b> Herkes, haklarını kullanırken dürüstlük kurallarına uymak zorundadır.</p></body></html>"
    raw_file.write_text(text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = sqlite3.connect(db_path)
    upsert_document(
        conn,
        "tr:legislation:law:4721",
        "legislation",
        "law",
        "TR",
        "Türk Medeni Kanunu",
        "4721",
        "fetched",
    )
    insert_artifact(
        conn,
        artifact_id="art-4721",
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

    # 2. Run Pipeline
    status = process_artifact_pipeline(artifact_id="art-4721")
    if status != "needs_review":
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT code, message, details_json FROM validation_issues")
        print("PIPELINE ISSUES:", c.fetchall())
        conn.close()
    assert status == "needs_review"

    # 3. Assert DB state
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM versions")
    assert c.fetchone()[0] == 1

    c.execute("SELECT count(*) FROM records")
    assert c.fetchone()[0] >= 2  # 1 legislation + articles
    conn.close()
