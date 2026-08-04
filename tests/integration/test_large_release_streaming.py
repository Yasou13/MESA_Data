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
from mesa_legal_data.release.importer import (
    ImportRollbackError,
    get_staging_connection,
    import_release_to_staging,
)
from mesa_legal_data.release.verifier import verify_release


def test_large_release_streaming_and_corrupt_rollback(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    staging_db = data_root / "mesa_staging.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(staging_db))

    db_path = get_db_path()
    migrate(None, db_path)

    # 1. Generate multi-article HTML fixture
    html_lines = ["<!DOCTYPE html><html><body>", "<h1>TÜRK MEDENİ KANUNU</h1>"]
    for i in range(1, 101):
        html_lines.append(f"<p><b>Madde {i}-</b> Bu bir test maddesidir numarası {i}.</p>")
    html_lines.append("</body></html>")
    html_text = "\n".join(html_lines)

    raw_dir = data_root / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashlarge"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"
    raw_file.write_text(html_text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-large-1",
        document_id="tr:legislation:law:4721",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/4721",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=byte_size,
        sha256=sha256,
        raw_path=str(raw_file.relative_to(data_root)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    process_artifact_pipeline(artifact_id="art-large-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Approved 100 articles")
    conn.close()

    # 2. Build Release 1
    rel1 = "rel-streaming-valid"
    meta1 = build_release(release_id=rel1)
    assert meta1["counts"]["article_count"] == 100

    assert verify_release(rel1) is True

    # Mark published
    conn = get_connection()
    conn.execute("UPDATE releases SET status = 'published' WHERE release_id = ?", (rel1,))
    conn.close()

    # Import Release 1
    res_imp1 = import_release_to_staging(rel1)
    assert res_imp1["status"] == "imported"

    # Verify active release pointer
    stg_conn = get_staging_connection()
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel1

    stg_cur.execute("SELECT count(*) FROM staging_records WHERE release_id = ?", (rel1,))
    assert stg_cur.fetchone()[0] == 102  # 1 legislation + 100 articles + 1 citation
    stg_conn.close()

    # 3. Build Release 2 & Corrupt a line in release data file
    rel2 = "rel-streaming-corrupt"
    build_release(release_id=rel2)

    conn = get_connection()
    conn.execute("UPDATE releases SET status = 'published' WHERE release_id = ?", (rel2,))
    conn.close()

    # Inject corrupt JSON line in data/articles.jsonl in rel2
    articles_file = data_root / "releases" / rel2 / "data" / "articles.jsonl"
    lines = articles_file.read_text(encoding="utf-8").splitlines()
    lines[50] = "CORRUPTED_NON_JSON_LINE_HERE"
    articles_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 4. Attempt import of corrupted release 2 -> MUST FAIL & ROLLBACK
    with pytest.raises((ImportRollbackError, Exception)):
        import_release_to_staging(rel2)

    # 5. Verify Active Release Pointer & Staging DB remains cleanly pointing to rel1!
    stg_conn = get_staging_connection()
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel1

    stg_cur.execute("SELECT count(*) FROM staging_records WHERE release_id = ?", (rel2,))
    assert stg_cur.fetchone()[0] == 0

    stg_cur.execute("SELECT status FROM imported_releases WHERE release_id = ?", (rel2,))
    assert stg_cur.fetchone() is None or stg_cur.fetchone()[0] != "imported"
    stg_conn.close()
