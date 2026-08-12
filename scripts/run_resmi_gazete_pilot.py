import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import mesa_legal_data.harvest.runner as harvest_runner
from mesa_legal_data.catalog import (
    approve_version_with_checks,
)
from mesa_legal_data.catalog import (
    get_connection as get_cat_conn,
)
from mesa_legal_data.catalog import (
    migrate as migrate_catalog,
)
from mesa_legal_data.harvest.config import load_harvest_config
from mesa_legal_data.harvest.discovery.resmi_gazete import ResmiGazeteDiscoveryAdapter
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.queue import (
    enqueue_discovered_document,
    get_harvest_item_by_id,
    reconcile_harvest_review_status,
)
from mesa_legal_data.harvest.runner import run_harvest_batch
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release, publish_release
from mesa_legal_data.release.importer import (
    get_record_provenance,
    get_staging_connection,
    import_release_to_staging,
    init_staging_db,
    rollback_release,
)
from mesa_legal_data.release.verifier import verify_release


def run_pilot():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        data_root = tmp_path / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        staging_db = data_root / "mesa_staging.sqlite"
        harvest_db = data_root / "harvest.sqlite"
        catalog_db = data_root / "catalog.sqlite"

        # Set environment variables for isolation
        os.environ["MESA_DATA_DATA_ROOT"] = str(data_root)
        os.environ["MESA_DATA_MESA_STAGING_DB"] = str(staging_db)
        os.environ["MESA_DATA_OPERATOR_CONTACT"] = "contact@mesalaw.org"
        os.environ["MESA_DATA_ENVIRONMENT"] = "development"

        print(f"=== Starting Real Bounded Resmî Gazete Pilot in {data_root} ===")

        # 1. Initialize catalog & harvest DB
        harvest_runner.check_free_disk_space = lambda minimum_free_bytes=0, custom_data_root=None: (
            True,
            100_000_000_000,
        )

        migrate_catalog(None, catalog_db)
        apply_harvest_migrations(harvest_db)

        from mesa_legal_data.catalog import create_release

        baseline_release_id = "rel-baseline-000"
        cat_conn_init = get_cat_conn(catalog_db)
        create_release(
            conn=cat_conn_init,
            release_id=baseline_release_id,
            release_path=f"releases/{baseline_release_id}",
            status="published",
            schema_version="1.0.0",
            counts_json="{}",
            source_snapshot_json="[]",
            manifest_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )
        cat_conn_init.close()

        # Seed staging DB with baseline release for real rollback transition validation
        stg_conn = get_staging_connection(staging_db)
        init_staging_db(stg_conn)
        now_iso = datetime.now(UTC).isoformat()
        stg_conn.execute(
            "INSERT INTO imported_releases (release_id, manifest_sha256, imported_at, status) VALUES (?, ?, ?, 'imported')",
            (baseline_release_id, "0000000000000000000000000000000000000000000000000000000000000000", now_iso),
        )
        stg_conn.execute(
            "INSERT INTO active_release (singleton_id, release_id, activated_at) VALUES (1, ?, ?)",
            (baseline_release_id, now_iso),
        )
        stg_conn.close()
        print("✓ Initialized catalog, harvest, and staging databases with baseline release.")

        # 2. Execute REAL Discovery Adapter against official Resmî Gazete endpoint
        adapter = ResmiGazeteDiscoveryAdapter()
        target_date = date(2026, 8, 1)
        print(f"✓ Attempting real HTTP discovery for date {target_date}...")

        discovered_docs = adapter.discover_date(target_date)
        if not discovered_docs:
            raise RuntimeError("Real discovery returned 0 documents for target date.")

        print(f"✓ Discovered {len(discovered_docs)} real documents.")
        doc = discovered_docs[0]
        print(f"✓ Target real document: title='{doc.title}', url='{doc.document_url}'")

        # 3. Enqueue discovered document through normal queue path
        from mesa_legal_data.harvest.models import SelectionDecision

        decision = SelectionDecision(accepted=True, priority=100, reasons=["real_discovery"])
        item, result_str = enqueue_discovered_document(
            doc=doc,
            adapter_name="resmi_gazete",
            decision=decision,
            db_path=harvest_db,
        )
        assert item is not None
        item_id = item.id
        print(f"✓ Enqueued real document item_id={item_id} (result={result_str}).")

        # 4. Run real harvest batch (real network download)
        harvest_cfg = load_harvest_config()
        batch_res = run_harvest_batch(harvest_cfg=harvest_cfg, batch_limit=1, db_path=harvest_db)
        print(f"✓ Harvest batch completed: {batch_res}")
        assert batch_res.get("succeeded", 0) > 0, "No documents succeeded harvest"

        item = get_harvest_item_by_id(item_id, db_path=harvest_db)
        print(f"✓ Harvest item status: {item.status}, artifact_id: {item.artifact_id}")
        assert item.artifact_id is not None

        # 5. Execute real pipeline processing
        pipe_status = process_artifact_pipeline(artifact_id=item.artifact_id)
        print(f"✓ Pipeline status: {pipe_status}")
        assert pipe_status in ("approved", "needs_review"), f"Unexpected pipeline status: {pipe_status}"

        # Check canonical records created in catalog
        cat_conn = get_cat_conn(catalog_db)
        cursor = cat_conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM records WHERE version_id IN (SELECT version_id FROM versions WHERE artifact_id = ?)",
            (item.artifact_id,),
        )
        canonical_count = cursor.fetchone()[0]
        cat_conn.close()
        print(f"✓ Canonical records generated in catalog: {canonical_count}")
        assert canonical_count > 0, "Canonical records count must be > 0"

        # 6. Catalog version approval via app API
        cat_conn = get_cat_conn(catalog_db)
        cursor = cat_conn.cursor()
        cursor.execute("SELECT version_id FROM versions WHERE artifact_id = ?", (item.artifact_id,))
        row = cursor.fetchone()
        assert row is not None
        version_id = row[0]

        app_res = approve_version_with_checks(cat_conn, version_id=version_id, reviewer="contact@mesalaw.org")
        cat_conn.close()
        print(f"✓ Version approval result: {app_res}")
        assert app_res["approved_records"] > 0, "Approved records count must be > 0"

        # Reconcile harvest review status
        reconciled = reconcile_harvest_review_status(version_id, db_path=harvest_db, catalog_db_path=catalog_db)
        item_final = get_harvest_item_by_id(item_id, db_path=harvest_db)
        print(f"✓ Harvest review status reconciled: {reconciled}, status={item_final.status}")
        assert item_final.status == "completed"

        # 7. Build release package
        pilot_release_id = "rel-rg-pilot-001"
        release_meta = build_release(release_id=pilot_release_id)
        counts = release_meta["counts"]
        total_release_records = sum(counts.values())
        print(f"✓ Built release: {release_meta['release_id']}, counts={counts}, total={total_release_records}")
        assert total_release_records > 0, "Release package must contain > 0 records"

        # 8. Trust anchor verification
        is_valid = verify_release(pilot_release_id)
        print(f"✓ Verified release trust anchor: {is_valid}")
        assert is_valid is True

        # Publish release via centralized publish_release() domain function
        pub_res = publish_release(pilot_release_id)
        print(
            f"✓ Published release via domain function: status={pub_res['status']}, published_at={pub_res['published_at']}"
        )

        # 9. Import release into staging DB
        stg_before = get_staging_connection(staging_db)
        cur = stg_before.cursor()
        cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
        active_before = cur.fetchone()[0]
        stg_before.close()
        print(f"✓ Active release before import: {active_before}")
        assert active_before == baseline_release_id

        imp_res = import_release_to_staging(pilot_release_id)
        imported_total = sum(imp_res["counts"].values())
        print(
            f"✓ Release imported into staging DB: status={imp_res['status']}, counts={imp_res['counts']}, total={imported_total}"
        )
        assert imp_res["status"] == "imported"
        assert imported_total > 0, "Staging imported records must be > 0"

        stg_after = get_staging_connection(staging_db)
        cur = stg_after.cursor()
        cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
        active_after_import = cur.fetchone()[0]
        stg_after.close()
        print(f"✓ Active release after import: {active_after_import}")
        assert active_after_import == pilot_release_id

        # 10. Idempotency test (re-import)
        imp_res_repeat = import_release_to_staging(pilot_release_id)
        print(f"✓ Re-imported release (idempotency check): status={imp_res_repeat['status']}")
        assert imp_res_repeat["status"] == "already_imported"

        # 11. Provenance & Record Continuity Check
        cat_conn = get_cat_conn(catalog_db)
        cursor = cat_conn.cursor()
        cursor.execute("SELECT record_id FROM release_items WHERE release_id = ? LIMIT 1", (pilot_release_id,))
        rec_row = cursor.fetchone()
        cat_conn.close()

        assert rec_row is not None, "No record found in release_items"
        tracked_record_id = rec_row[0]
        prov = get_record_provenance(tracked_record_id)
        print(f"✓ Tracked pilot record provenance for '{tracked_record_id}':")
        print(f"   - active_release_id: {prov.get('active_release_id')}")
        print(f"   - in_active_release: {prov.get('in_active_release')}")
        print(f"   - version_id: {prov.get('version_id')}")
        print(f"   - source_id: {prov.get('source_id')}")
        print(f"   - source_url: {prov.get('source_url')}")
        assert prov.get("active_release_id") == pilot_release_id
        assert prov.get("in_active_release") is True

        # 12. Rollback test to baseline release
        roll_res = rollback_release(baseline_release_id)
        print(f"✓ Rollback executed: status={roll_res['status']}")

        stg_final = get_staging_connection(staging_db)
        cur = stg_final.cursor()
        cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
        active_after_rollback = cur.fetchone()[0]
        stg_final.close()
        print(f"✓ Active release after rollback: {active_after_rollback}")
        assert active_after_rollback == baseline_release_id, (
            f"Expected active release {baseline_release_id}, got {active_after_rollback}"
        )

        # Verify provenance after rollback: tracked_record_id is no longer in active release
        prov_post_rollback = get_record_provenance(tracked_record_id)
        print(
            f"✓ Provenance post-rollback for '{tracked_record_id}': active={prov_post_rollback.get('active_release_id')}, in_active={prov_post_rollback.get('in_active_release')}"
        )
        assert prov_post_rollback.get("active_release_id") == baseline_release_id
        assert prov_post_rollback.get("in_active_release") is False

        print("\n=== REAL RESMÎ GAZETE PILOT COMPLETED SUCCESSFULLY ===")


if __name__ == "__main__":
    run_pilot()
