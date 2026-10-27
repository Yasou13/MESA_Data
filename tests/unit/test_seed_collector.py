import sqlite3

from typer.testing import CliRunner

from mesa_legal_data.catalog import get_db_path
from mesa_legal_data.cli import app
from mesa_legal_data.collectors.seed import load_seed_config

runner = CliRunner()


def test_load_seed_config():
    items = load_seed_config()
    assert len(items) >= 35
    numbers = [i["number"] for i in items]
    assert "4721" in numbers
    assert "2709" in numbers
    assert "6502" in numbers


def test_collect_seed_and_report_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Init & Migrate
    runner.invoke(app, ["init"])
    runner.invoke(app, ["migrate"])

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at) "
        "VALUES ('mevzuat', 'Mevzuat', 'Gov', 'http://mevzuat.gov.tr', 'manual', 1, '1.0', '{}', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    # Create dummy local PDF fixtures
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    items = load_seed_config()
    for item in items:
        num = item["number"]
        pdf_file = fixtures_dir / f"{num}.pdf"
        pdf_file.write_bytes(f"%PDF-1.4\nFixture Content for law {num}".encode())

    result = runner.invoke(app, ["collect", "seed", "--fixtures-dir", str(fixtures_dir)])
    assert result.exit_code == 0, f"Error output: {result.output}"
    assert f"Successfully collected {len(items)} seed legislation artifacts" in result.output

    # Test report command
    rep_result = runner.invoke(app, ["report"])
    assert rep_result.exit_code == 0
    assert f"Total Documents: {len(items)}" in rep_result.output
    assert f"Total Artifacts: {len(items)}" in rep_result.output


def test_seed_collector_snapshot_date_and_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Init & Migrate
    runner.invoke(app, ["init"])
    runner.invoke(app, ["migrate"])

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at) "
        "VALUES ('mevzuat', 'Mevzuat', 'Gov', 'http://mevzuat.gov.tr', 'manual', 1, '1.0', '{}', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    # Create dummy local PDF fixture for 4721 with valid text layer
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    pdf_file = fixtures_dir / "4721.pdf"
    pdf_file.write_bytes(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length 44 >>\nstream\nBT\n/F1 12 Tf\n100 700 Td\n(Madde 1 - Baslik) Tj\nET\nendstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000241 00000 n \n0000000339 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n409\n%%EOF\n"
    )

    seed_yaml = tmp_path / "seed.yaml"
    seed_yaml.write_text(
        """
seed_legislation:
  - number: "4721"
    document_id: "tr:legislation:law:4721"
    title: "Türk Medeni Kanunu"
    type: "law"
    source_url: "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4721.pdf"
"""
    )

    from mesa_legal_data.collectors.seed import run_seed_collection

    artifacts = run_seed_collection(config_path=seed_yaml, local_fixtures_dir=fixtures_dir)
    assert len(artifacts) == 1

    art = artifacts[0]
    assert art.metadata.get("snapshot_date") is not None
    assert art.metadata.get("source_role") == "consolidated_text"

    # Check pipeline created a version
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT version_id, approval_status FROM versions WHERE document_id = 'tr:legislation:law:4721'")
    row = cursor.fetchone()
    assert row is not None, "Pipeline must run and create a version for the new artifact"
    conn.close()

    # Running collect seed twice with same bytes creates no second artifact and no second version
    run_seed_collection(config_path=seed_yaml, local_fixtures_dir=fixtures_dir)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM artifacts WHERE document_id = 'tr:legislation:law:4721'")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT count(*) FROM versions WHERE document_id = 'tr:legislation:law:4721'")
    assert cursor.fetchone()[0] == 1
    conn.close()
