import hashlib
import json

from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    migrate,
)
from mesa_legal_data.exports import generate_export_package
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.release.builder import build_release


def test_operations_scale_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    # 1. Create raw artifact file
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "scale_sample.html"
    raw_file.write_text("<!DOCTYPE html><html><body><h1>MADDE 1: Scale Test</h1></body></html>", encoding="utf-8")
    with open(raw_file, "rb") as f:
        sha = hash_stream(f)

    # 2. Batch insert 500 records
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc-scale-1', 'legislation', 'law', 'TR', 'Scale Test Law', 'scale-key-1', 'fetched', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art-scale-1', 'doc-scale-1', 'mevzuat', 'https://example.com/scale.html', '2026-08-05T00:00:00Z', 'manual', 200, 'text/html', 'text/html', 10, ?, 'raw/scale_sample.html', 'fetched', '{}')""",
        (sha,),
    )

    canon_dir = tmp_path / "canonical"
    canon_dir.mkdir(parents=True, exist_ok=True)
    canon_file = canon_dir / "scale.jsonl"

    v_ids = []
    with open(canon_file, "w", encoding="utf-8") as f_canon:
        for i in range(1, 501):
            v_id = f"ver-scale-{i}"
            v_ids.append(v_id)
            r_id = f"rec-scale-{i}"
            line_str = (
                json.dumps(
                    {
                        "id": r_id,
                        "record_type": "article",
                        "legislation_id": "doc-scale-1",
                        "article_number": str(i),
                        "article_kind": "madde",
                        "text": f"Article text {i}",
                        "status": "yürürlükte",
                        "schema_version": "1.0.0",
                        "created_at": "2026-08-05T00:00:00Z",
                        "source": {
                            "source_id": "mevzuat",
                            "source_url": "https://example.com/scale.html",
                            "retrieved_at": "2026-08-05T00:00:00Z",
                            "artifact_sha256": sha,
                        },
                        "provenance": {
                            "parser_name": "scale_parser",
                            "parser_version": "1.0",
                            "pipeline_run_id": "scale-run-1",
                        },
                    }
                )
                + "\n"
            )
            rec_sha = hashlib.sha256(line_str.encode("utf-8")).hexdigest()

            c.execute(
                """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
                   VALUES (?, 'doc-scale-1', 'art-scale-1', 'snapshot', 'canonical/scale.jsonl', ?, 'sha-v-scale', 'parser_scale', '1.0', '1.0', 'valid', 'clean', 'pending', '2026-08-05T00:00:00Z')""",
                (v_id, i),
            )
            c.execute(
                """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
                   VALUES (?, ?, 'article', 'canonical/scale.jsonl', ?, ?, 'valid', 'pending', '2026-08-05T00:00:00Z')""",
                (r_id, v_id, i, rec_sha),
            )
            f_canon.write(line_str)

    conn.commit()

    # 3. Bulk streaming approval of 500 versions
    for v_id in v_ids:
        approve_version_streaming(conn, version_id=v_id, reviewer="scale_bot", note="Approved at scale")

    c.execute("SELECT COUNT(*) FROM records WHERE approval_status = 'approved'")
    assert c.fetchone()[0] == 500

    # 4. Large export streaming test
    res_exp = generate_export_package(
        conn,
        export_id="exp-scale-1",
        export_type="records_csv",
        actor="scale_bot",
    )
    assert res_exp["export_id"] == "exp-scale-1"
    exp_p = tmp_path / res_exp["export_path"]
    assert exp_p.exists()
    assert exp_p.stat().st_size > 1000

    conn.close()

    # 5. Build release with 500 records
    res_rel = build_release(release_id="rel-scale-500")
    assert res_rel["release_id"] == "rel-scale-500"
    assert res_rel["status"] == "verified"
