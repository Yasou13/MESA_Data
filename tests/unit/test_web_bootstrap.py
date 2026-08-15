import sqlite3
from pathlib import Path

from mesa_legal_data.catalog import get_connection
from mesa_legal_data.web.bootstrap import prepare_web_runtime


def test_prepare_web_runtime_creates_stores(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "test_data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    prepare_web_runtime(custom_data_root=data_root)

    assert (data_root / "raw").exists()
    assert (data_root / "canonical").exists()
    assert (data_root / "releases").exists()
    assert (data_root / "tmp").exists()
    assert (data_root / "exports").exists()
    assert (data_root / "catalog.sqlite").exists()
    assert (data_root / "harvest" / "harvest.sqlite").exists()

    # Verify tables exist
    conn = sqlite3.connect(data_root / "catalog.sqlite")
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='documents'")
    assert c.fetchone() is not None
    conn.close()


def test_prepare_web_runtime_idempotent(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "test_data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    prepare_web_runtime(custom_data_root=data_root)
    # Insert dummy document
    conn = get_connection(data_root / "catalog.sqlite")
    conn.execute(
        "INSERT INTO documents (document_id, family, document_type, jurisdiction, stable_key, title, lifecycle_status, created_at, updated_at) VALUES ('doc1', 'legislation', 'law', 'TR', 'k1', 'Test', 'fetched', 'now', 'now')"
    )
    conn.close()

    # Run second time
    prepare_web_runtime(custom_data_root=data_root)

    # Document should still exist
    conn = get_connection(data_root / "catalog.sqlite")
    c = conn.cursor()
    c.execute("SELECT document_id FROM documents WHERE document_id='doc1'")
    assert c.fetchone() is not None
    conn.close()


def test_prepare_web_runtime_recovers_interrupted_operations(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "test_data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    prepare_web_runtime(custom_data_root=data_root)

    # Insert a running operation
    conn = get_connection(data_root / "catalog.sqlite")
    conn.execute(
        "INSERT INTO operation_jobs (operation_id, operation_type, requested_by, status, input_json, progress_current, progress_total, created_at) VALUES ('op-stuck', 'filtered_export', 'user', 'running', '{}', 10, 100, 'now')"
    )
    conn.close()

    # Run bootstrap again
    prepare_web_runtime(custom_data_root=data_root)

    # Status should be 'interrupted'
    conn = get_connection(data_root / "catalog.sqlite")
    c = conn.cursor()
    c.execute("SELECT status FROM operation_jobs WHERE operation_id='op-stuck'")
    row = c.fetchone()
    assert row is not None
    assert row[0] == "interrupted"
    conn.close()
