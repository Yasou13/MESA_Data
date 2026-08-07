from pathlib import Path

from mesa_legal_data.harvest.config import HarvestConfig
from mesa_legal_data.harvest.discovery.manifest import import_manifest_file
from mesa_legal_data.harvest.migrations import apply_harvest_migrations


def test_manifest_csv_import(tmp_path: Path):
    db_file = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_file)

    csv_file = tmp_path / "urls.csv"
    csv_file.write_text(
        "source_id,canonical_key,document_id,family,document_type,title,url,publication_date,priority\n"
        "resmi_gazete,rg:2026-08-07:law:1,tr:legislation:law:1,legislation,law,Law 1,https://example.gov.tr/law1.pdf,2026-08-07,100\n"
        "resmi_gazete,rg:2026-08-07:law:2,tr:legislation:law:2,legislation,law,Law 2,https://example.gov.tr/law2.pdf,2026-08-07,100\n",
        encoding="utf-8",
    )

    cfg = HarvestConfig()
    stats = import_manifest_file(csv_file, cfg, db_path=db_file)
    assert stats["total"] == 2
    assert stats["inserted"] == 2
    assert stats["duplicate"] == 0

    # Re-importing same file should mark all as duplicate
    stats_dup = import_manifest_file(csv_file, cfg, db_path=db_file)
    assert stats_dup["total"] == 2
    assert stats_dup["inserted"] == 0
    assert stats_dup["duplicate"] == 2
