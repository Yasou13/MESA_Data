from datetime import UTC, datetime, timedelta
from pathlib import Path

import respx

from mesa_legal_data.catalog import get_db_path as get_catalog_db_path
from mesa_legal_data.catalog import migrate as run_catalog_migrations
from mesa_legal_data.harvest.config import HarvestConfig, HarvestSourceConfig
from mesa_legal_data.harvest.database import get_harvest_connection, get_harvest_db_path
from mesa_legal_data.harvest.discovery.manifest import import_manifest_file
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.queue import (
    acquire_lease_batch,
    recover_expired_leases,
    update_item_status,
)
from mesa_legal_data.harvest.runner import run_harvest_batch


@respx.mock
def test_manifest_queue_collect_pipeline_retry_recovery_e2e(tmp_path: Path, monkeypatch):
    """
    End-to-end acceptance test:
    manifest -> queue -> collect URL -> pipeline -> retry -> restart recovery
    """
    # Override DATA_ROOT for test sandbox using correct env prefix
    sandbox_data = tmp_path / "data_root"
    sandbox_data.mkdir(parents=True, exist_ok=True)
    (sandbox_data / "raw").mkdir(parents=True, exist_ok=True)
    (sandbox_data / "canonical").mkdir(parents=True, exist_ok=True)
    (sandbox_data / "releases").mkdir(parents=True, exist_ok=True)
    (sandbox_data / "tmp").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(sandbox_data))

    # Initialize core catalog db and harvest db
    catalog_db = get_catalog_db_path()
    run_catalog_migrations(db_path=catalog_db)

    db_path = get_harvest_db_path(sandbox_data)
    apply_harvest_migrations(db_path)

    # 1. Setup mock URLs on allowed host www.resmigazete.gov.tr
    url1 = "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-1.htm"
    url2 = "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-2.htm"
    url_broken = "https://www.resmigazete.gov.tr/eskiler/2026/08/broken.htm"

    respx.get(url1).respond(
        status_code=200,
        headers={"content-type": "text/html"},
        content=b"<html><body><h1>7500 SAYILI KANUN</h1><p>Madde 1 - Bu kanun test amaclidir.</p></body></html>",
    )
    respx.get(url2).respond(
        status_code=200,
        headers={"content-type": "text/html"},
        content=b"<html><body><h1>7501 SAYILI KANUN</h1><p>Madde 1 - Bu ikinci kanun test amaclidir.</p></body></html>",
    )
    respx.get(url_broken).respond(status_code=503)

    # 2. Create manifest CSV pointing to unique allowed URLs
    manifest_csv = tmp_path / "manifest.csv"
    manifest_csv.write_text(
        "source_id,canonical_key,document_id,family,document_type,title,url,publication_date,priority\n"
        f"resmi_gazete,rg:2026-08-07:law:7500,tr:legislation:law:7500,legislation,law,7500 Sayili Kanun,{url1},2026-08-07,150\n"
        f"resmi_gazete,rg:2026-08-07:law:7501,tr:legislation:law:7501,legislation,law,7501 Sayili Kanun,{url2},2026-08-07,100\n",
        encoding="utf-8",
    )

    # 3. Import Manifest into Queue
    cfg = HarvestConfig()
    cfg.target.minimum_free_disk_bytes = 1000  # Sandbox test override
    cfg.sources["resmi_gazete"] = HarvestSourceConfig(
        enabled=True,
        adapter="manifest",
        source_id="resmi_gazete",
    )

    stats = import_manifest_file(manifest_csv, cfg, db_path=db_path)
    assert stats["inserted"] == 2

    # 4. Verify Atomic Lease
    leased = acquire_lease_batch("worker-test", batch_size=1, db_path=db_path)
    assert len(leased) == 1
    item1 = leased[0]
    assert item1.status == "leased"
    assert item1.document_id == "tr:legislation:law:7500"

    # Reset back to queued for full batch run test
    update_item_status(item1.id, "queued", db_path=db_path)

    # 5. Run Harvest Batch (Collect URL -> Pipeline execution)
    batch_res = run_harvest_batch(
        harvest_cfg=cfg,
        batch_limit=2,
        db_path=db_path,
        custom_data_root=sandbox_data,
    )
    assert batch_res["processed"] == 2
    assert batch_res["succeeded"] == 2

    # Verify status in harvest.sqlite
    conn = get_harvest_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, artifact_id, raw_bytes FROM harvest_items WHERE id = ?",
        (item1.id,),
    )
    row = cursor.fetchone()
    assert row["status"] in ("needs_review", "completed")
    assert row["artifact_id"].startswith("sha256:")
    assert row["raw_bytes"] > 0
    conn.close()

    # 6. Test Retry Flow
    manifest_broken = tmp_path / "broken.csv"
    manifest_broken.write_text(
        "source_id,canonical_key,document_id,family,document_type,title,url,publication_date,priority\n"
        f"resmi_gazete,rg:2026-08-07:law:9999,tr:legislation:law:9999,legislation,law,Broken Law,{url_broken},2026-08-07,200\n",
        encoding="utf-8",
    )
    import_manifest_file(manifest_broken, cfg, db_path=db_path)

    batch_broken = run_harvest_batch(
        harvest_cfg=cfg,
        batch_limit=1,
        db_path=db_path,
        custom_data_root=sandbox_data,
    )
    assert batch_broken["processed"] == 1
    assert batch_broken["retry_wait"] == 1

    # 7. Test Restart Recovery (Expired Leases)
    # Simulate a crashed worker leaving an item leased with expired timestamp
    cursor_conn = get_harvest_connection(db_path)
    old_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    cursor_conn.execute(
        "UPDATE harvest_items SET status = 'leased', lease_owner = 'dead-worker', lease_expires_at = ? WHERE canonical_key = 'rg:2026-08-07:law:9999'",
        (old_time,),
    )
    cursor_conn.commit()
    cursor_conn.close()

    # Trigger recovery
    recovered_count = recover_expired_leases(db_path=db_path)
    assert recovered_count == 1

    conn_rec = get_harvest_connection(db_path)
    rec_row = conn_rec.execute(
        "SELECT status, lease_owner FROM harvest_items WHERE canonical_key = 'rg:2026-08-07:law:9999'"
    ).fetchone()
    assert rec_row["status"] == "queued"
    assert rec_row["lease_owner"] is None
    conn_rec.close()
