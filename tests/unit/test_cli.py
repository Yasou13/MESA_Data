import os
from pathlib import Path
from typer.testing import CliRunner
from mesa_legal_data.cli import app

runner = CliRunner()

def test_init_command(monkeypatch, tmp_path):
    # Use tmp_path as data root
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Data root initialized" in result.stdout
    
    assert (tmp_path / "raw").exists()
    assert (tmp_path / "canonical").exists()
    assert (tmp_path / "releases").exists()
    assert (tmp_path / "tmp").exists()
    
    # Running again should be safe
    result2 = runner.invoke(app, ["init"])
    assert result2.exit_code == 0
