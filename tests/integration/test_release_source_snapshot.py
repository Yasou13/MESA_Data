from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release


def test_release_source_snapshot_exact(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_mevzuat = tmp_path / "raw" / "mevzuat.html"
    raw_mevzuat.parent.mkdir(parents=True, exist_ok=True)
    raw_mevzuat.write_text(
        "<!DOCTYPE html><html><body><h1>Kanun 1</h1><p><b>Madde 1-</b> Kanun uygulanır.</p></body></html>",
        encoding="utf-8",
    )
    with open(raw_mevzuat, "rb") as f:
        sha_mev = hash_stream(f)

    raw_aym = tmp_path / "raw" / "aym.html"
    raw_aym.write_text(
        "<!DOCTYPE html><html><body><h1>AYM Kararı</h1><p><b>Madde 1-</b> Anayasa mahkemesi kararı.</p></body></html>",
        encoding="utf-8",
    )
    with open(raw_aym, "rb") as f:
        sha_aym = hash_stream(f)

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:1", "legislation", "law", "TR", "Law 1", "1", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-mevzuat-1",
        document_id="tr:legislation:law:1",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/law1.pdf",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_mevzuat.stat().st_size,
        sha256=sha_mev,
        raw_path=str(raw_mevzuat.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )

    upsert_document(conn, "tr:decision:aym:1", "decision", "aym_decision", "TR", "AYM 1", "2026/1", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-aym-1",
        document_id="tr:decision:aym:1",
        source_id="aym",
        source_url="https://kararlarbilgibankasi.anayasa.gov.tr/1",
        retrieved_at="2026-08-05T01:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_aym.stat().st_size,
        sha256=sha_aym,
        raw_path=str(raw_aym.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    process_artifact_pipeline(artifact_id="art-mevzuat-1")
    process_artifact_pipeline(artifact_id="art-aym-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT version_id FROM records")
    v_ids = [r[0] for r in c.fetchall()]
    for vid in v_ids:
        approve_version_streaming(conn, version_id=vid, reviewer="test_user", note="Approved")
    conn.close()

    rel_meta = build_release(release_id="rel-source-test-01")
    source_snap = rel_meta["source_snapshot"]

    assert len(source_snap) == 2
    sources_found = {s["source_id"]: s for s in source_snap}
    assert "mevzuat" in sources_found
    assert "aym" in sources_found
    assert sources_found["mevzuat"]["record_count"] >= 1
    assert sources_found["aym"]["record_count"] >= 1
    assert "policy_version" in sources_found["mevzuat"]
    assert "latest_retrieved_at" in sources_found["mevzuat"]
