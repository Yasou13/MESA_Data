from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.web.app import create_app


def test_web_review_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashwr"
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
        artifact_id="art-wr-1",
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

    process_artifact_pipeline(artifact_id="art-wr-1")

    app = create_app()
    client = TestClient(app)

    # 1. Get pending records
    res_recs = client.get("/api/records?approval_status=pending")
    assert res_recs.status_code == 200
    records = res_recs.json()["data"]["items"]
    assert len(records) >= 1

    r_id = records[0]["record_id"]
    ver_id = records[0]["version_id"]

    # 2. Get Record Detail
    res_detail = client.get(f"/api/records/{r_id}")
    assert res_detail.status_code == 200
    assert "text_preview" in res_detail.json()["data"]

    # 3. Approve Version via API
    res_app = client.post(
        f"/api/versions/{ver_id}/approve",
        json={"reviewer": "yasin", "note": "Verified"},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_app.status_code == 200
    assert res_app.json()["data"]["status"] == "approved"
