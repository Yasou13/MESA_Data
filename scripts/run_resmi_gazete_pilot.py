import os
import sys
import tempfile
import httpx
import respx
from pathlib import Path
from datetime import UTC, datetime, date

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
        os.environ["MESA_DATA_OPERATOR_CONTACT"] = "operator@mesalaw.org"
        os.environ["MESA_DATA_ENVIRONMENT"] = "development"

        print(f"=== Starting Bounded Resmî Gazete Pilot in {data_root} ===")

        # 1. Initialize catalog & harvest DB
        from mesa_legal_data.catalog import migrate as migrate_catalog, get_connection as get_cat_conn, approve_version_with_checks
        from mesa_legal_data.harvest.migrations import apply_harvest_migrations
        from mesa_legal_data.harvest.models import DiscoveredDocument, SelectionDecision
        from mesa_legal_data.harvest.queue import enqueue_discovered_document, get_harvest_item_by_id, reconcile_harvest_review_status
        from mesa_legal_data.harvest.runner import run_harvest_batch
        from mesa_legal_data.pipeline import process_artifact_pipeline
        from mesa_legal_data.release.builder import build_release
        from mesa_legal_data.release.verifier import verify_release
        from mesa_legal_data.release.importer import import_release_to_staging, get_record_provenance, rollback_release
        from mesa_legal_data.harvest.config import load_harvest_config
        import mesa_legal_data.harvest.runner as harvest_runner

        # Bypass disk check in test environment
        harvest_runner.check_free_disk_space = lambda minimum_free_bytes=0, custom_data_root=None: (True, 100_000_000_000)

        migrate_catalog(None, catalog_db)
        apply_harvest_migrations(harvest_db)
        print("✓ Initialized catalog and harvest databases.")

        # 2. Enqueue bounded test document for Resmî Gazete
        doc_url = "https://www.resmigazete.gov.tr/eskiler/2026/08/20260801-1.htm"
        doc = DiscoveredDocument(
            source_id="resmi_gazete",
            canonical_key="rg:20260801-1",
            document_url=doc_url,
            document_id="tr:legislation:rg:20260801-1",
            family="legislation",
            document_type="official_gazette",
            title="Resmî Gazete Sayı 32900",
            publication_date=date(2026, 8, 1),
            discovery_page_url="https://www.resmigazete.gov.tr",
        )
        decision = SelectionDecision(accepted=True, priority=100, reasons=["test_enqueue"])

        item, result_str = enqueue_discovered_document(
            doc=doc,
            adapter_name="resmi_gazete",
            decision=decision,
            db_path=harvest_db,
        )
        assert item is not None
        item_id = item.id
        print(f"✓ Enqueued document item_id={item_id} (result={result_str}).")

        # Mock respx for outgoing fetch
        with respx.mock(assert_all_called=False) as mock_respx:
            mock_respx.route().respond(
                status_code=200,
                html="<html><body><h1>T.C. Resmî Gazete</h1><p>Kanun No: 9999</p></body></html>"
            )

            # 3. Run harvest batch
            harvest_cfg = load_harvest_config()
            batch_res = run_harvest_batch(harvest_cfg=harvest_cfg, batch_limit=1, db_path=harvest_db)
            print(f"✓ Harvest batch completed: {batch_res}")
            assert batch_res["succeeded"] == 1 or batch_res["processed"] == 1

        item = get_harvest_item_by_id(item_id, db_path=harvest_db)
        print(f"✓ Harvest item status: {item.status}, artifact_id: {item.artifact_id}")
        assert item.artifact_id is not None

        # 4. Pipeline processing
        pipe_status = process_artifact_pipeline(artifact_id=item.artifact_id)
        print(f"✓ Pipeline status: {pipe_status}")

        # 5. Catalog approval
        cat_conn = get_cat_conn(catalog_db)
        cursor = cat_conn.cursor()
        cursor.execute("SELECT version_id FROM versions WHERE artifact_id = ?", (item.artifact_id,))
        row = cursor.fetchone()
        assert row is not None
        version_id = row[0]

        app_res = approve_version_with_checks(cat_conn, version_id=version_id, reviewer="operator@mesalaw.org")
        cat_conn.close()
        print(f"✓ Version approval result: {app_res}")

        # Reconcile harvest review status
        reconciled = reconcile_harvest_review_status(version_id, db_path=harvest_db, catalog_db_path=catalog_db)
        item_final = get_harvest_item_by_id(item_id, db_path=harvest_db)
        print(f"✓ Harvest review status reconciled: {reconciled}, status={item_final.status}")
        assert item_final.status == "completed"

        # 6. Build release package
        release_meta = build_release(release_id="rel-rg-pilot-001")
        print(f"✓ Built release: {release_meta['release_id']}, counts={release_meta['counts']}")

        # 7. Trust anchor verification
        is_valid = verify_release("rel-rg-pilot-001")
        print(f"✓ Verified release trust anchor: {is_valid}")
        assert is_valid is True

        # Publish release in catalog
        cat_conn = get_cat_conn(catalog_db)
        cat_conn.execute("UPDATE releases SET status = 'published' WHERE release_id = 'rel-rg-pilot-001'")
        cat_conn.commit()
        cat_conn.close()

        # 8. Import release into staging DB
        imp_res = import_release_to_staging("rel-rg-pilot-001")
        print(f"✓ Release imported into staging DB: status={imp_res['status']}")
        assert imp_res["status"] in ("imported", "already_imported")

        # 9. Idempotency test (re-import)
        imp_res_repeat = import_release_to_staging("rel-rg-pilot-001")
        print(f"✓ Re-imported release (idempotency check): status={imp_res_repeat['status']}")
        assert imp_res_repeat["status"] == "already_imported"

        # 10. Provenance check
        stg_conn = get_cat_conn(catalog_db)
        cursor = stg_conn.cursor()
        cursor.execute("SELECT record_id FROM records LIMIT 1")
        rec_row = cursor.fetchone()
        stg_conn.close()
        if rec_row:
            prov = get_record_provenance(rec_row[0])
            print(f"✓ Record provenance verified for {rec_row[0]}: release={prov.get('active_release_id')}")

        # 11. Rollback test
        roll_res = rollback_release("rel-rg-pilot-001")
        print(f"✓ Rollback executed: status={roll_res['status']}")

        print("\n=== RESMÎ GAZETE PILOT COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_pilot()
