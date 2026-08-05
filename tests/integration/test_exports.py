import csv
import json

from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.exports import generate_export_package
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline


def test_export_types_and_filters(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_file = tmp_path / "raw" / "exp_test.html"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(
        "<!DOCTYPE html><html><body><h1>Export Test</h1><p><b>Madde 1-</b> Export content.</p></body></html>",
        encoding="utf-8",
    )
    with open(raw_file, "rb") as f:
        sha = hash_stream(f)

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:888", "legislation", "law", "TR", "Law 888", "888", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-exp-888",
        document_id="tr:legislation:law:888",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/888.pdf",
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

    process_artifact_pipeline(artifact_id="art-exp-888")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM records LIMIT 1")
    v_id = c.fetchone()[0]
    approve_version_streaming(conn, version_id=v_id, reviewer="exporter", note="Approved")

    # 1. Export records_jsonl
    res_jsonl = generate_export_package(
        conn,
        export_id="exp-test-jsonl",
        export_type="records_jsonl",
        filters={"record_type": "legislation"},
        actor="exporter",
    )
    assert res_jsonl["record_count"] >= 1
    abs_p = tmp_path / res_jsonl["relative_path"]
    assert abs_p.exists()
    lines = abs_p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    rec_obj = json.loads(lines[0])
    assert "id" in rec_obj or "record_id" in rec_obj or "title" in rec_obj

    # 2. Export records_csv
    res_csv = generate_export_package(
        conn,
        export_id="exp-test-csv",
        export_type="records_csv",
        filters={},
        actor="exporter",
    )
    assert res_csv["record_count"] >= 1
    abs_csv_p = tmp_path / res_csv["relative_path"]
    with open(abs_csv_p, "r", encoding="utf-8") as csv_f:
        reader = csv.reader(csv_f)
        header = next(reader)
        assert "record_id" in header
        rows = list(reader)
        assert len(rows) >= 1

    # 3. Export empty result -> valid empty file
    res_empty = generate_export_package(
        conn,
        export_id="exp-test-empty",
        export_type="records_jsonl",
        filters={"record_type": "non_existent_type"},
        actor="exporter",
    )
    assert res_empty["record_count"] == 0
    abs_empty_p = tmp_path / res_empty["relative_path"]
    assert abs_empty_p.exists()
    assert abs_empty_p.read_text(encoding="utf-8") == ""

    conn.close()
