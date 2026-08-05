from fastapi.testclient import TestClient

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
from mesa_legal_data.web.app import create_app


def test_all_download_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_file = tmp_path / "raw" / "dl_test.html"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(
        "<!DOCTYPE html><html><body><h1>Title</h1><p><b>Madde 1-</b> Content.</p></body></html>", encoding="utf-8"
    )
    with open(raw_file, "rb") as f:
        sha = hash_stream(f)

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:777", "legislation", "law", "TR", "Law 777", "777", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-dl-777",
        document_id="tr:legislation:law:777",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/777.pdf",
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

    process_artifact_pipeline(artifact_id="art-dl-777")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT record_id, version_id FROM records LIMIT 1")
    r_id, v_id = c.fetchone()
    approve_version_streaming(conn, version_id=v_id, reviewer="dl_user", note="Approved")
    conn.close()

    app = create_app()
    client = TestClient(app)

    # 1. Artifact raw download
    r_art = client.get("/api/artifacts/art-dl-777/download")
    assert r_art.status_code == 200

    # 2. Artifact metadata download
    r_meta = client.get("/api/artifacts/art-dl-777/metadata/download")
    assert r_meta.status_code == 200
    assert r_meta.json()["artifact_id"] == "art-dl-777"

    # 3. Record download (JSON)
    r_rec_json = client.get(f"/api/records/{r_id}/download?format=json")
    assert r_rec_json.status_code == 200
    assert r_rec_json.json()["id"] == r_id

    # 4. Record download (Text)
    r_rec_txt = client.get(f"/api/records/{r_id}/download?format=text")
    assert r_rec_txt.status_code == 200
    assert len(r_rec_txt.text) > 0

    # 5. Provenance download
    r_prov = client.get(f"/api/provenance/{r_id}/download")
    assert r_prov.status_code == 200
    assert r_prov.json()["record_id"] == r_id
