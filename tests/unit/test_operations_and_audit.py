import sqlite3
from pathlib import Path
from typer.testing import CliRunner

from mesa_legal_data.cli import app
from mesa_legal_data.catalog import get_db_path
from mesa_legal_data.audit import run_doctor_check, backup_catalog, restore_catalog, run_integrity_audit

runner = CliRunner()

def test_operations_and_audit_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # 1. Init & Migrate
    runner.invoke(app, ["init"])
    runner.invoke(app, ["migrate"])

    # 2. Test Doctor CLI
    res = runner.invoke(app, ["doctor"])
    assert res.exit_code == 0
    assert "HEALTH CHECK" in res.output.upper()

    # 3. Test Backup CLI
    b_dir = tmp_path / "backups"
    res_b = runner.invoke(app, ["backup", "--target-dir", str(b_dir)])
    assert res_b.exit_code == 0
    assert "Successfully backed up catalog" in res_b.output

    backup_file = list(b_dir.glob("*.sqlite"))[0]

    # 4. Test Restore CLI
    res_r = runner.invoke(app, ["restore", "--backup-file", str(backup_file)])
    assert res_r.exit_code == 0
    assert "Successfully restored catalog" in res_r.output

    # 5. Test Audit CLI
    res_a = runner.invoke(app, ["audit"])
    assert res_a.exit_code == 0
    assert "PASSED CLEAN" in res_a.output.upper()
