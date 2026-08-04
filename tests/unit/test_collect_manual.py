import sqlite3

from typer.testing import CliRunner

from mesa_legal_data.catalog import get_db_path
from mesa_legal_data.cli import app

runner = CliRunner()


def test_collect_manual_cli(tmp_path, monkeypatch):
    # 1. Setup isolated data root
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Init directories and migrate catalog
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["migrate"])
    assert result.exit_code == 0

    # Insert a dummy source into SQLite to satisfy FK
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at) "
        "VALUES ('mevzuat', 'Mevzuat', 'Gov', 'http://mevzuat.gov.tr', 'manual', 1, '1.0', '{}', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    # 2. Create sample test PDF fixture
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    fixture_file = fixture_dir / "4721.pdf"
    fixture_file.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")

    # 3. Run CLI command
    result = runner.invoke(
        app,
        [
            "collect",
            "manual",
            "--source",
            "mevzuat",
            "--file",
            str(fixture_file),
            "--document-id",
            "tr:legislation:law:4721",
        ],
    )

    assert result.exit_code == 0, f"Command output: {result.output}"
    assert "Successfully imported artifact" in result.output

    # 4. Verify catalog DB contains records
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM documents WHERE document_id = 'tr:legislation:law:4721'")
    assert cursor.fetchone()[0] == 1

    cursor.execute("SELECT count(*) FROM artifacts WHERE document_id = 'tr:legislation:law:4721'")
    assert cursor.fetchone()[0] == 1

    cursor.execute("SELECT raw_path FROM artifacts WHERE document_id = 'tr:legislation:law:4721'")
    raw_path_str = cursor.fetchone()[0]
    full_raw_path = tmp_path / raw_path_str
    assert full_raw_path.exists()
    assert full_raw_path.parent / "metadata.json" in list(full_raw_path.parent.iterdir())
    conn.close()
