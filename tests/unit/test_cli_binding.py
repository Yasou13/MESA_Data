from typer.testing import CliRunner

from mesa_legal_data.cli import app

runner = CliRunner()


def test_web_cli_binding_loopback_default():
    result = runner.invoke(app, ["web", "--help"])
    assert result.exit_code == 0
    assert "127.0.0.1" in result.stdout


def test_web_cli_binding_non_loopback_without_token_fails(monkeypatch):
    monkeypatch.delenv("MESA_DATA_WEB_ADMIN_TOKEN", raising=False)
    result = runner.invoke(app, ["web", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "MESA_DATA_WEB_ADMIN_TOKEN" in result.stdout or "ERROR" in result.stdout
