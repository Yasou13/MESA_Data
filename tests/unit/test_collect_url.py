import sqlite3
import respx
from pathlib import Path
from typer.testing import CliRunner

from mesa_legal_data.cli import app
from mesa_legal_data.catalog import get_db_path

runner = CliRunner()

@respx.mock
def test_collect_url_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Init & Migrate
    runner.invoke(app, ["init"])
    runner.invoke(app, ["migrate"])

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at) "
        "VALUES ('mevzuat', 'Mevzuat', 'Gov', 'http://mevzuat.gov.tr', 'manual', 1, '1.0', '{}', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    target_url = "http://example.com/law_4721.pdf"
    respx.get(target_url).respond(
        status_code=200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-1.4\nSample Law Content",
    )

    result = runner.invoke(
        app,
        [
            "collect",
            "url",
            "--source",
            "mevzuat",
            "--url",
            target_url,
            "--document-id",
            "tr:legislation:law:4721",
        ],
    )

    assert result.exit_code == 0, f"Command output: {result.output}"
    assert "Successfully imported URL artifact" in result.output

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM artifacts WHERE document_id = 'tr:legislation:law:4721'")
    assert cursor.fetchone()[0] == 1
    conn.close()
