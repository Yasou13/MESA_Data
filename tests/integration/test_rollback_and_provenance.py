from mesa_legal_data.catalog import (
    approve_version_with_checks,
    get_connection,
    get_db_path,
    insert_artifact,
    mark_release_status,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release
from mesa_legal_data.release.importer import (
    get_record_provenance,
    get_staging_connection,
    import_release_to_staging,
    rollback_release,
)


def test_rollback_and_provenance_integration(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(tmp_path / "mesa_staging.sqlite"))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashroll"
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
        artifact_id="art-roll-1",
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

    process_artifact_pipeline(artifact_id="art-roll-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Approved")
    conn.close()

    # 1. Build and Import Release 1
    rel1 = "rel-roll-1"
    build_release(release_id=rel1)
    conn = get_connection()
    mark_release_status(conn, rel1, "published")
    conn.close()
    import_release_to_staging(rel1)

    # 2. Build and Import Release 2
    rel2 = "rel-roll-2"
    build_release(release_id=rel2)
    conn = get_connection()
    mark_release_status(conn, rel2, "published")
    conn.close()
    import_release_to_staging(rel2)

    # Verify active release is rel2
    stg_conn = get_staging_connection()
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel2
    stg_conn.close()

    # 3. Rollback active release to rel1
    res_roll = rollback_release(rel1)
    assert res_roll["status"] == "rolled_back"
    assert res_roll["active_release_id"] == rel1

    # Verify active release pointer is back to rel1
    stg_conn = get_staging_connection()
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel1
    stg_conn.close()

    # 4. Provenance check
    prov = get_record_provenance("tr:legislation:law:4721")
    assert prov["active_release_id"] == rel1
    assert prov["record_id"] == "tr:legislation:law:4721"
    assert prov["source_id"] == "mevzuat"
    assert prov["raw_sha256"] == sha256
