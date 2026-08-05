import json

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    migrate,
)
from mesa_legal_data.exports import generate_export_package


def test_large_export_streaming(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    canon_dir = tmp_path / "canonical"
    canon_dir.mkdir(parents=True, exist_ok=True)
    canon_file = canon_dir / "bulk.jsonl"

    lines = []
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc-bulk', 'legislation', 'law', 'TR', 'Bulk Law', 'key-bulk', 'fetched', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art-bulk', 'doc-bulk', 'mevzuat', 'https://example.com/bulk.html', '2026-08-05T00:00:00Z', 'manual', 200, 'text/html', 'text/html', 10, 'sha-bulk-99', 'raw/bulk.html', 'fetched', '{}')"""
    )
    c.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
           VALUES ('ver-bulk', 'doc-bulk', 'art-bulk', 'snapshot', 'canonical/bulk.jsonl', 1, 'sha-ver-99', 'test_parser', '1.0', '1.0', 'valid', 'clean', 'approved', '2026-08-05T00:00:00Z')"""
    )

    # Insert 100 mock records
    for i in range(100):
        rec_id = f"tr:legislation:law:bulk:{i}"
        rec_obj = {"id": rec_id, "type": "article", "text": f"Article text {i}"}
        lines.append(json.dumps(rec_obj) + "\n")
        line_num = i + 1
        c.execute(
            """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
               VALUES (?, 'ver-bulk', 'article', 'canonical/bulk.jsonl', ?, ?, 'valid', 'approved', '2026-08-05T00:00:00Z')""",
            (rec_id, line_num, f"sha-rec-{i}"),
        )
    canon_file.write_text("".join(lines), encoding="utf-8")
    conn.commit()

    res = generate_export_package(
        conn,
        export_id="exp-bulk-100",
        export_type="records_jsonl",
        filters={},
        actor="bulk_tester",
    )
    conn.close()

    assert res["record_count"] == 100
    out_p = tmp_path / res["relative_path"]
    assert out_p.exists()
    out_lines = out_p.read_text(encoding="utf-8").strip().splitlines()
    assert len(out_lines) == 100
