from fastapi.testclient import TestClient

from mesa_legal_data.catalog import get_db_path, migrate
from mesa_legal_data.web.app import create_app


def test_web_system_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app()
    client = TestClient(app)

    # 1. System Doctor API
    res_doc = client.post(
        "/api/system/doctor",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_doc.status_code == 200
    assert res_doc.json()["data"]["data_root_writable"] is True

    # 2. System Status API
    res_stat = client.get("/api/system/status")
    assert res_stat.status_code == 200

    # 3. System Backup API
    res_back = client.post(
        "/api/system/backup",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_back.status_code == 200
    assert "backup_path" in res_back.json()["data"]
