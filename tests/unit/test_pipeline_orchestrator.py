import sqlite3
import pytest
from pathlib import Path

from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.catalog import get_db_path, migrate

def test_pipeline_orchestrator(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    migrate(migrations_dir, db_path)

    # 1. Create a dummy raw payload
    raw_dir = tmp_path / "raw" / "legislation"
    raw_dir.mkdir(parents=True)
    payload = raw_dir / "payload.html"
    content = "<html><body>MADDE 1 - Hukukun uygulanmasi.</body></html>".encode("utf-8")
    payload.write_bytes(content)

    import hashlib
    sha256 = hashlib.sha256(content).hexdigest()
    byte_size = len(content)

    status = process_artifact_pipeline(
        artifact_id="art-test",
        raw_path_str="raw/legislation/payload.html",
        document_id="tr:legislation:law:4721",
        family="legislation",
        sha256=sha256,
        byte_size=byte_size,
        detected_mime="text/html",
    )

    assert status == "approved"
