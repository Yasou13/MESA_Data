import sqlite3
from pathlib import Path

from mesa_legal_data.catalog import get_db_path, migrate
from mesa_legal_data.parsers import parse_decision_text, parse_html
from mesa_legal_data.sources.aym import import_aym_decision


def test_aym_golden_import_and_parse(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    migrate(migrations_dir, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at) "
        "VALUES ('aym', 'AYM', 'Gov', 'http://kararlarbilgibankasi.anayasa.gov.tr', 'manual', 1, '1.0', '{}', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    golden_file = Path(__file__).parent.parent / "golden" / "aym" / "sample_bb.html"

    artifact = import_aym_decision(
        file_path=golden_file,
        kind="bb",
        application_year=2021,
        application_number=18822,
    )

    assert artifact.document_id == "tr:case-law:aym:bb:2021-18822"

    # Verify parser extracts contents
    content = golden_file.read_text(encoding="utf-8")
    text = parse_html(content)
    parsed = parse_decision_text(text)

    assert parsed.court == "ANAYASA MAHKEMESİ"
    assert "adil yargılanma hakkı" in parsed.text
