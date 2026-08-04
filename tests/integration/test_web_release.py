from fastapi.testclient import TestClient

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
from mesa_legal_data.web.app import create_app


def test_web_release_and_import_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(tmp_path / "mesa_staging.sqlite"))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashwrel"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    text = "<!DOCTYPE html><html><body>\n<h1>TÜRK MEDENİ KANUNU</h1>\n<p><b>Madde 1-</b> Kanun uygulanır.</p>\n</body></html>"
    raw_file.write_text(text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-wrel-1",
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

    process_artifact_pipeline(artifact_id="art-wrel-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Approved")
    conn.close()

    app = create_app()
    client = TestClient(app)

    rel_id = "rel-web-1"

    # 1. Build Release via API
    res_b = client.post(
        "/api/releases",
        json={"release_id": rel_id},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_b.status_code == 200
    assert res_b.json()["data"]["release_id"] == rel_id

    # 2. Verify Release via API
    res_v = client.post(
        f"/api/releases/{rel_id}/verify",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_v.status_code == 200
    assert res_v.json()["data"]["verified"] is True

    # 3. Publish Release via API
    res_p = client.post(
        f"/api/releases/{rel_id}/publish",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_p.status_code == 200
    assert res_p.json()["data"]["status"] == "published"

    # 4. Import Release via API
    res_i = client.post(
        f"/api/releases/{rel_id}/import",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_i.status_code == 200
    assert res_i.json()["data"]["status"] == "imported"

    # 5. Provenance via API
    res_prov = client.get("/api/provenance/tr:legislation:law:4721")
    assert res_prov.status_code == 200
    assert res_prov.json()["data"]["active_release_id"] == rel_id
