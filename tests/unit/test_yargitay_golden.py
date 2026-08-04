import sqlite3
from pathlib import Path

from mesa_legal_data.sources.yargitay import import_yargitay_decision
from mesa_legal_data.parsers import parse_decision_text, parse_html, extract_citations
from mesa_legal_data.catalog import get_db_path, migrate

def test_yargitay_golden_import_and_parse(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    migrate(migrations_dir, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at) "
        "VALUES ('yargitay', 'Yargitay', 'Gov', 'http://karararama.yargitay.gov.tr', 'manual', 1, '1.0', '{}', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    golden_file = Path(__file__).parent.parent / "golden" / "yargitay" / "sample_decision.html"

    artifact = import_yargitay_decision(
        file_path=golden_file,
        chamber="3hd",
        case_year=2023,
        case_seq=4125,
        decision_year=2024,
        decision_seq=1872,
    )

    assert artifact.document_id == "tr:case-law:yargitay:3hd:2023-4125:2024-1872"

    content = golden_file.read_text(encoding="utf-8")
    text = parse_html(content)
    parsed = parse_decision_text(text)

    assert parsed.court == "YARGITAY"
    assert "3. HUKUK DAİRESİ" in parsed.chamber
    assert parsed.esas_no == "2023/4125"

    citations = extract_citations(text)
    assert len(citations) >= 1
    assert citations[0].target_legislation_id == "tr:legislation:law:6098"
    assert citations[0].target_article_id == "tr:legislation:law:6098:article:117"
