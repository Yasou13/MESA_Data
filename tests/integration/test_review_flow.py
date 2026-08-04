from mesa_legal_data.catalog import (
    approve_version_with_checks,
    get_connection,
    get_db_path,
    get_record,
    get_version,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline


def test_review_flow_integration(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashrev"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    text = "<!DOCTYPE html><html><body><h1>TÜRK MEDENİ KANUNU</h1><p><b>Madde 1-</b> Kanun uygulanır.</p></body></html>"
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
        artifact_id="art-rev-1",
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

    status = process_artifact_pipeline(artifact_id="art-rev-1")
    assert status == "needs_review"

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]

    c.execute("SELECT record_id FROM records WHERE version_id = ?", (ver_id,))
    r_ids = [r[0] for r in c.fetchall()]
    assert len(r_ids) >= 1

    # Approve whole version
    res = approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Kontrol edildi")
    assert res["status"] == "approved"

    ver_obj = get_version(conn, ver_id)
    assert ver_obj["approval_status"] == "approved"

    rec_obj = get_record(conn, r_ids[0])
    assert rec_obj["approval_status"] == "approved"
    conn.close()
