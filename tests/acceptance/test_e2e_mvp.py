from typer.testing import CliRunner

from mesa_legal_data.catalog import (
    get_connection,
    insert_artifact,
    mark_release_status,
    upsert_document,
)
from mesa_legal_data.cli import app
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release import build_release, verify_release
from mesa_legal_data.release.importer import (
    get_record_provenance,
    get_staging_connection,
    import_release_to_staging,
    rollback_release,
)

runner = CliRunner()


def test_e2e_mvp_acceptance_flow(tmp_path, monkeypatch):
    """
    Master end-to-end acceptance test for MESA Legal Data MVP.
    Verifies full chain: init -> migrate -> raw import -> pipeline -> review -> release -> verify -> publish -> staging import -> idempotency -> rollback -> provenance.
    """
    data_root = tmp_path / "data"
    staging_db = tmp_path / "data" / "mesa_staging.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(staging_db))

    # 1. CLI init & migrate
    res_init = runner.invoke(app, ["init"])
    assert res_init.exit_code == 0

    res_mig = runner.invoke(app, ["migrate"])
    assert res_mig.exit_code == 0

    # 2. Raw Synthetic Law Import
    raw_dir = data_root / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hash_e2e"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    text = (
        "<!DOCTYPE html><html><body>\n"
        "<h1>TÜRK MEDENİ KANUNU</h1>\n"
        "<p><b>Madde 1-</b> Kanun, sözüyle ve özüyle değindiği bütün konularda uygulanır.</p>\n"
        "<p><b>Madde 2-</b> Herkes, haklarını kullanırken dürüstlük kurallarına uymak zorundadır.</p>\n"
        "</body></html>"
    )
    raw_file.write_text(text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = get_connection()
    upsert_document(
        conn,
        "tr:legislation:law:4721",
        "legislation",
        "law",
        "TR",
        "Türk Medeni Kanunu",
        "4721",
        "fetched",
    )
    insert_artifact(
        conn,
        artifact_id="art-e2e-1",
        document_id="tr:legislation:law:4721",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/4721",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=byte_size,
        sha256=sha256,
        raw_path=str(raw_file.relative_to(data_root)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    # 3. Pipeline Run
    status = process_artifact_pipeline("art-e2e-1")
    assert status == "needs_review"

    # Assert canonical files and records
    canonical_files = list((data_root / "canonical").glob("**/*.jsonl"))
    assert len(canonical_files) >= 1

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    conn.close()

    # 4. Review & Approval via CLI
    res_app = runner.invoke(
        app,
        [
            "review",
            "approve-version",
            ver_id,
            "--reviewer",
            "yasin",
            "--note",
            "Verified",
        ],
    )
    assert res_app.exit_code == 0
    assert "APPROVED" in res_app.output

    # 5. Build Release Package
    rel1_id = "legal-core-2026-v1"
    rel_meta = build_release(release_id=rel1_id)
    assert rel_meta["release_id"] == rel1_id
    assert rel_meta["counts"]["legislation_count"] == 1
    assert rel_meta["counts"]["article_count"] == 2

    # 6. Verify Release
    assert verify_release(rel1_id) is True

    # 7. Publish Release
    conn = get_connection()
    mark_release_status(conn, rel1_id, "published")
    conn.close()

    # 8. Import Release to MESA Staging DB
    res_imp1 = import_release_to_staging(rel1_id)
    assert res_imp1["status"] == "imported"

    # Assert staging records
    stg_conn = get_staging_connection(staging_db)
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT count(*) FROM staging_records WHERE release_id = ?", (rel1_id,))
    assert stg_cur.fetchone()[0] >= 3  # 1 legislation + 2 articles

    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel1_id
    stg_conn.close()

    # 9. Idempotency Check
    res_imp2 = import_release_to_staging(rel1_id)
    assert res_imp2["status"] == "already_imported"

    # 10. Provenance Query
    prov = get_record_provenance("tr:legislation:law:4721")
    assert prov["active_release_id"] == rel1_id
    assert prov["raw_sha256"] == sha256

    # 11. Second Release & Rollback
    rel2_id = "legal-core-2026-v2"
    build_release(release_id=rel2_id)
    conn = get_connection()
    mark_release_status(conn, rel2_id, "published")
    conn.close()

    import_release_to_staging(rel2_id)

    stg_conn = get_staging_connection(staging_db)
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel2_id
    stg_conn.close()

    # Rollback to rel1_id
    res_roll = rollback_release(rel1_id)
    assert res_roll["status"] == "rolled_back"

    stg_conn = get_staging_connection(staging_db)
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel1_id
    stg_conn.close()
