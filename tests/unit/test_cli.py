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


def test_source_cli_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(tmp_path / "mesa_staging.sqlite"))

    # Init and migrate
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["migrate"]).exit_code == 0

    from mesa_legal_data.catalog import (
        get_connection,
        get_parser_certification,
        get_source_operational_settings,
    )

    # 1. source show default
    res = runner.invoke(app, ["source", "show", "mevzuat"])
    assert res.exit_code == 0
    assert "Source Operational Settings: mevzuat" in res.stdout
    assert "Auto-approval Enabled  : False" in res.stdout

    # 2. source auto-approval --enable
    res = runner.invoke(app, ["source", "auto-approval", "mevzuat", "--enable", "--by", "test_admin"])
    assert res.exit_code == 0
    assert "Auto-approval enabled for source 'mevzuat' by test_admin." in res.stdout

    conn = get_connection()
    try:
        settings = get_source_operational_settings(conn, "mevzuat")
        assert settings["auto_approval_enabled"] is True
        assert settings["updated_by"] == "test_admin"
        assert settings["enabled"] is True
        assert settings["weekly_sample_count"] == 10
    finally:
        conn.close()

    # 3. source auto-approval --disable
    res = runner.invoke(app, ["source", "auto-approval", "mevzuat", "--disable", "--by", "test_admin2"])
    assert res.exit_code == 0
    assert "Auto-approval disabled for source 'mevzuat' by test_admin2." in res.stdout

    conn = get_connection()
    try:
        settings = get_source_operational_settings(conn, "mevzuat")
        assert settings["auto_approval_enabled"] is False
        assert settings["updated_by"] == "test_admin2"
    finally:
        conn.close()

    # 4. source certify-parser
    res = runner.invoke(
        app,
        [
            "source",
            "certify-parser",
            "mevzuat",
            "--parser",
            "legislation_parser",
            "--version",
            "1.1.0",
            "--by",
            "certifier_user",
        ],
    )
    assert res.exit_code == 0
    assert "Parser 'legislation_parser' v1.1.0 certified for source 'mevzuat' by certifier_user." in res.stdout

    conn = get_connection()
    try:
        assert get_parser_certification(conn, "mevzuat", "legislation_parser", "1.1.0") is True
    finally:
        conn.close()

    # Check show now reflects certified parser
    res = runner.invoke(app, ["source", "show", "mevzuat"])
    assert res.exit_code == 0
    assert "legislation_parser v1.1.0" in res.stdout
    assert "CERTIFIED" in res.stdout

    # 5. source certify-parser --revoke
    res = runner.invoke(
        app,
        [
            "source",
            "certify-parser",
            "mevzuat",
            "--parser",
            "legislation_parser",
            "--version",
            "1.1.0",
            "--by",
            "revoker_user",
            "--revoke",
        ],
    )
    assert res.exit_code == 0
    assert "Parser 'legislation_parser' v1.1.0 revoked for source 'mevzuat' by revoker_user." in res.stdout

    conn = get_connection()
    try:
        assert get_parser_certification(conn, "mevzuat", "legislation_parser", "1.1.0") is False
    finally:
        conn.close()
