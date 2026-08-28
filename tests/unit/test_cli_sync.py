from typer.testing import CliRunner

from mesa_legal_data.catalog import get_connection, migrate
from mesa_legal_data.cli import app


def test_cli_sync_stops_before_mesa_push(tmp_path, monkeypatch):
    runner = CliRunner()
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "catalog.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    migrate(None, db_path)

    result = runner.invoke(app, ["sync", "--source", "resmi_gazete", "--max-items", "5"])

    assert result.exit_code == 0
    assert "Starting MESA Legal Data Synchronization Pipeline" in result.output
    assert "Sync Summary" in result.output
    # Verify the explicit warning / notice that it stops before MESA push
    assert "stopped before MESA push" in result.output

    # Verify no deliveries were automatically pushed into mesa_deliveries
    conn = get_connection(db_path)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM mesa_deliveries")
    del_count = c.fetchone()[0]
    conn.close()
    assert del_count == 0
