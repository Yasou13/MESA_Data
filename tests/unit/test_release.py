from typer.testing import CliRunner

from mesa_legal_data.cli import app

runner = CliRunner()


def test_release_lifecycle_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Init & Migrate
    runner.invoke(app, ["init"])
    runner.invoke(app, ["migrate"])

    rel_id = "rel-v1.0"

    # Build release
    res = runner.invoke(app, ["release", "build", "--release-id", rel_id])
    assert res.exit_code == 0, res.output

    # Verify release
    res_verify = runner.invoke(app, ["release", "verify", "--release-id", rel_id])
    assert res_verify.exit_code == 0, res_verify.output

    # Publish release
    res_pub = runner.invoke(app, ["release", "publish", "--release-id", rel_id])
    assert res_pub.exit_code == 0, res_pub.output

    # Revoke release
    res_rev = runner.invoke(app, ["release", "revoke", "--release-id", rel_id])
    assert res_rev.exit_code == 0, res_rev.output
