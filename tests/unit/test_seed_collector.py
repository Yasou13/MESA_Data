import sqlite3
import respx
from pathlib import Path
from typer.testing import CliRunner

from mesa_legal_data.cli import app
from mesa_legal_data.catalog import get_db_path
from mesa_legal_data.collectors.seed import load_seed_config

runner = CliRunner()

def test_load_seed_config():
    items = load_seed_config()
    assert len(items) == 12
    numbers = [i["number"] for i in items]
    assert "4721" in numbers
    assert "2709" in numbers

def test_collect_seed_and_report_cli(tmp_path, monkeypatch):
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

    # Create dummy local PDF fixtures
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    for num in ["2709", "4721", "6098", "6100", "2004", "5237", "5271", "4857", "6102", "2577", "1136", "6698"]:
        pdf_file = fixtures_dir / f"{num}.pdf"
        pdf_file.write_bytes(f"%PDF-1.4\nFixture Content for law {num}".encode("utf-8"))

    result = runner.invoke(app, ["collect", "seed", "--fixtures-dir", str(fixtures_dir)])
    assert result.exit_code == 0, f"Error output: {result.output}"
    assert "Successfully collected 12 seed legislation artifacts" in result.output

    # Test report command
    rep_result = runner.invoke(app, ["report"])
    assert rep_result.exit_code == 0
    assert "Total Documents: 12" in rep_result.output
    assert "Total Artifacts: 12" in rep_result.output
