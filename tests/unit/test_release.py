from typer.testing import CliRunner

from mesa_legal_data.cli import app

runner = CliRunner()


def test_release_lifecycle_cli(tmp_path, monkeypatch):
    import hashlib
    import json
    from datetime import UTC, datetime

    from mesa_legal_data.catalog import get_connection, insert_artifact, upsert_document, upsert_source

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Init & Migrate
    runner.invoke(app, ["init"])
    runner.invoke(app, ["migrate"])

    db_path = tmp_path / "catalog.sqlite"
    conn = get_connection(db_path)
    now = datetime.now(UTC).isoformat()
    valid_sha = "0000000000000000000000000000000000000000000000000000000000000000"
    upsert_source(conn, "resmi_gazete", "RG", "Auth", "https://example.com")
    upsert_document(conn, "doc1", "legislation", "law", "TR", "Test Law", "key1", "approved")
    insert_artifact(
        conn,
        "art1",
        "doc1",
        "resmi_gazete",
        "https://example.com/1",
        now,
        "http",
        200,
        "text/html",
        "text/html",
        100,
        valid_sha,
        "raw/1.html",
        None,
        None,
        "success",
        None,
        "{}",
    )

    c_dir = tmp_path / "canonical"
    c_dir.mkdir(parents=True, exist_ok=True)
    c_file = c_dir / "test.jsonl"
    rec_obj = {
        "id": "rec1",
        "record_type": "legislation",
        "jurisdiction": "TR",
        "language": "tr",
        "legislation_type": "law",
        "number": "1",
        "title": "Test Law",
        "short_title": None,
        "publication": None,
        "status": "active",
        "version": {
            "version_id": "ver1",
            "version_kind": "consolidated_snapshot",
            "snapshot_date": "2026-08-11",
            "effective_from": None,
            "effective_to": None,
        },
        "full_text": "Text",
        "schema_version": "1.0.0",
        "created_at": now,
        "source": {
            "source_id": "resmi_gazete",
            "source_url": "https://example.com/1",
            "retrieved_at": now,
            "artifact_sha256": valid_sha,
            "artifact_path": "raw/1.html",
        },
        "provenance": {
            "parser_name": "legislation_parser",
            "parser_version": "1.0.0",
            "pipeline_run_id": "run-1",
        },
    }
    line_str = json.dumps(rec_obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    c_file.write_text(line_str, encoding="utf-8")
    rec_sha = hashlib.sha256(line_str.encode("utf-8")).hexdigest()

    conn.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, snapshot_date, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
           VALUES ('ver1', 'doc1', 'art1', 'snapshot', '2026-08-11', 'canonical/test.jsonl', 1, ?, 'p', '1', '1.0.0', 'valid', 'clean', 'approved', ?)""",
        (rec_sha, now),
    )
    conn.execute(
        """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('rec1', 'ver1', 'legislation', 'canonical/test.jsonl', 1, ?, 'valid', 'approved', ?)""",
        (rec_sha, now),
    )
    conn.commit()
    conn.close()

    rel_id = "rel-v1.0"

    # Build release
    res = runner.invoke(app, ["release", "build", "--release-id", rel_id])
    assert res.exit_code == 0, res.output

    # Verify release
    res_verify = runner.invoke(app, ["release", "verify", "--release-id", rel_id])
    assert res_verify.exit_code == 0, res_verify.output

    # Publish release
    res_pub = runner.invoke(app, ["release", "publish", "--release-id", rel_id])
    assert res_pub.exit_code == 0, res_pub.output

    # Revoke release
    res_rev = runner.invoke(app, ["release", "revoke", "--release-id", rel_id])
    assert res_rev.exit_code == 0, res_rev.output
