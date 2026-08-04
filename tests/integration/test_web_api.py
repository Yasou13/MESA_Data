from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    migrate,
    upsert_document,
)
from mesa_legal_data.web.app import create_app


def test_web_api_dashboard_and_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(tmp_path / "mesa_staging.sqlite"))

    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app()
    client = TestClient(app)

    # 1. Health check
    res_h = client.get("/api/health")
    assert res_h.status_code == 200
    assert res_h.json()["data"]["status"] == "ok"

    # 2. Empty dashboard
    res_d = client.get("/api/dashboard")
    assert res_d.status_code == 200
    assert res_d.json()["data"]["counts"]["documents"] == 0

    # 3. Public config
    res_cfg = client.get("/api/config/public")
    assert res_cfg.status_code == 200
    assert "environment" in res_cfg.json()["data"]

    # 4. Insert synthetic document & query
    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")
    conn.close()

    res_docs = client.get("/api/documents")
    assert res_docs.status_code == 200
    assert res_docs.json()["data"]["total"] == 1
    assert res_docs.json()["data"]["items"][0]["document_id"] == "tr:legislation:law:4721"

    res_doc_detail = client.get("/api/documents/tr:legislation:law:4721")
    assert res_doc_detail.status_code == 200
    assert res_doc_detail.json()["data"]["title"] == "TMK"
