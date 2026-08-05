from fastapi.testclient import TestClient

from mesa_legal_data.audit import backup_catalog, restore_catalog, run_doctor_check
from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    migrate,
    upsert_document,
)
from mesa_legal_data.web.app import create_app


def test_full_backup_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:111", "legislation", "law", "TR", "Backup Law", "111", "fetched")
    conn.close()

    # 1. Backup catalog
    backup_file = backup_catalog()
    assert backup_file.exists()

    # 2. Modify original DB
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM documents WHERE document_id = 'tr:legislation:law:111'")
    conn.commit()
    conn.close()

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM documents WHERE document_id = 'tr:legislation:law:111'")
    assert c.fetchone()[0] == 0
    conn.close()

    # 3. Restore catalog from backup
    restore_success = restore_catalog(backup_file)
    assert restore_success is True

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM documents WHERE document_id = 'tr:legislation:law:111'")
    assert c.fetchone()[0] == 1
    conn.close()

    # 4. Doctor check health
    health = run_doctor_check()
    assert health["catalog_sqlite_healthy"] is True

    # 5. HTTP Admin Backup endpoint
    app = create_app()
    client = TestClient(app)
    res_bck = client.post("/api/admin/backup", headers={"X-MESA-Requested-With": "web-admin", "X-MESA-Actor": "admin"})
    assert res_bck.status_code == 200
    assert "backup_path" in res_bck.json()["data"]
