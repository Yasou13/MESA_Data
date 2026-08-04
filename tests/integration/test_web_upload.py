from fastapi.testclient import TestClient

from mesa_legal_data.catalog import get_connection, get_db_path, migrate
from mesa_legal_data.web.app import create_app


def test_web_upload_file_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app()
    client = TestClient(app)

    # File Upload
    file_content = (
        "<!DOCTYPE html><html><body><h1>TÜRK MEDENİ KANUNU</h1><p><b>Madde 1-</b> Kanun.</p></body></html>".encode(
            "utf-8"
        )
    )
    res_up = client.post(
        "/api/artifacts/upload",
        data={
            "source_id": "mevzuat",
            "document_id": "tr:legislation:law:4721",
            "family": "legislation",
            "document_type": "law",
            "title": "TMK",
        },
        files={"file": ("payload.html", file_content, "text/html")},
        headers={"X-MESA-Requested-With": "web-admin"},
    )

    assert res_up.status_code == 200, f"Response: {res_up.text}"
    art_id = res_up.json()["data"]["artifact_id"]
    assert art_id.startswith("sha256:")

    # Verify DB catalog has artifact
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT count(*) FROM artifacts WHERE artifact_id = ?", (art_id,))
    assert c.fetchone()[0] == 1
    conn.close()
