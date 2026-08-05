import hashlib
import json

from fastapi.testclient import TestClient

from mesa_legal_data.audit import log_audit_event, run_doctor_check, run_integrity_audit
from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    insert_artifact,
    list_records_by_approval_status,
    mark_release_status,
    migrate,
    upsert_document,
)
from mesa_legal_data.exports import generate_export_package
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release
from mesa_legal_data.release.importer import get_record_provenance, import_release_to_staging
from mesa_legal_data.release.verifier import verify_release
from mesa_legal_data.web.app import create_app


def test_feature_freeze_gate_complete_workflow(tmp_path, monkeypatch):
    """
    FREEZE-011: Complete Feature Freeze Gate acceptance test covering all 18 steps.
    """
    # 1. Temporary data root
    data_root = tmp_path / "freeze_gate_root"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    # 2. Init / Migrate
    db_path = get_db_path()
    migrate(None, db_path)

    # 3. Dosya yükle (Upload / Seed artifact)
    raw_dir = data_root / "raw" / "legislation"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "kanun100.html"
    raw_content = "<!DOCTYPE html><html><body><h1>Kanun 100</h1><p><b>Madde 1-</b> Madde bir icerigi.</p></body></html>"
    raw_file.write_text(raw_content, encoding="utf-8")
    with open(raw_file, "rb") as f:
        raw_hash = hash_stream(f)

    conn = get_connection()
    upsert_document(
        conn,
        document_id="tr:legislation:law:100",
        family="legislation",
        document_type="law",
        jurisdiction="TR",
        title="Kanun 100",
        stable_key="kanun-100",
        lifecycle_status="fetched",
    )
    insert_artifact(
        conn,
        artifact_id="art-gate-100",
        document_id="tr:legislation:law:100",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/100.html",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_file.stat().st_size,
        sha256=raw_hash,
        raw_path=str(raw_file.relative_to(data_root)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    log_audit_event(
        conn,
        actor="gate_tester",
        action="upload",
        subject_type="artifact",
        subject_id="art-gate-100",
        new_sha256=raw_hash,
    )
    conn.close()

    # 4. Pipeline execution
    v_id = process_artifact_pipeline(artifact_id="art-gate-100")
    assert v_id is not None

    # 5. Canonical kayıtları doğrula
    conn = get_connection()
    recs = list_records_by_approval_status(conn)
    assert len(recs) >= 1
    rec = recs[0]
    record_id = rec["record_id"]
    version_id = rec["version_id"]
    canonical_rel_path = rec["canonical_path"]
    assert (data_root / canonical_rel_path).exists()
    conn.close()

    # 6. Bulk approve version
    conn = get_connection()
    approve_res = approve_version_streaming(conn, version_id=version_id, reviewer="gate_reviewer", note="Approved")
    assert approve_res["approved_records"] >= 1
    conn.close()

    # 7. Records JSONL export
    conn = get_connection()
    exp_res = generate_export_package(
        conn,
        export_id="exp-gate-100",
        export_type="records_jsonl",
        filters={},
        actor="gate_exporter",
    )
    conn.close()
    assert exp_res["status"] == "ready"
    assert exp_res["record_count"] >= 1

    # 8. Export içeriğini doğrula
    exp_abs_path = data_root / exp_res["relative_path"]
    assert exp_abs_path.exists()
    with open(exp_abs_path, "r", encoding="utf-8") as f:
        export_lines = f.readlines()
    assert len(export_lines) >= 1
    first_record_json = json.loads(export_lines[0])
    assert "type" in first_record_json or "id" in first_record_json or "text" in first_record_json

    # 9. Release build, verify, publish
    rel_build_res = build_release(release_id="rel-gate-v1.0.0")
    assert rel_build_res["status"] == "building" or rel_build_res["release_id"] == "rel-gate-v1.0.0"

    is_verified = verify_release("rel-gate-v1.0.0")
    assert is_verified is True

    conn = get_connection()
    mark_release_status(conn, release_id="rel-gate-v1.0.0", status="published", published_at="2026-08-05T00:00:00Z")
    conn.close()

    # 10. Staging import
    import_res = import_release_to_staging(release_id="rel-gate-v1.0.0")
    assert import_res["status"] in ("imported", "already_imported")

    # 11. Provenance
    prov_data = get_record_provenance(record_id)
    assert prov_data is not None
    assert prov_data["record_id"] == record_id

    # 12. Artifact download & SHA-256 verification
    app = create_app()
    client = TestClient(app)
    headers = {"X-MESA-Requested-With": "web-admin", "X-MESA-Actor": "gate_downloader"}

    res_dl = client.get("/api/artifacts/art-gate-100/download", headers=headers)
    assert res_dl.status_code == 200
    assert hashlib.sha256(res_dl.content).hexdigest() == raw_hash

    # 13. Release package download
    res_pkg = client.get("/api/releases/rel-gate-v1.0.0/package", headers=headers)
    assert res_pkg.status_code == 200
    assert len(res_pkg.content) > 0

    # 14. Integrity audit operation
    audit_res = run_integrity_audit()
    assert audit_res["corrupted"] == 0

    # 15. Audit event kapsamı
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT action FROM audit_events")
    recorded_actions = {r[0] for r in c.fetchall()}
    conn.close()
    assert "upload" in recorded_actions
    assert "version_approve" in recorded_actions
    assert "export_create" in recorded_actions

    # 16. Unsupported operation fail (400)
    res_unsupported_op = client.post(
        "/api/operations/jobs",
        json={"operation_type": "revalidate", "input": {}},
        headers=headers,
    )
    assert res_unsupported_op.status_code == 400
    assert res_unsupported_op.json()["error"]["code"] == "OPERATION_TYPE_NOT_SUPPORTED"

    # 17. Unsupported export fail (400)
    res_unsupported_exp = client.post(
        "/api/exports",
        json={"export_type": "legislation_jsonl", "filters": {}},
        headers=headers,
    )
    assert res_unsupported_exp.status_code == 400
    assert res_unsupported_exp.json()["error"]["code"] == "EXPORT_TYPE_NOT_SUPPORTED"

    # 18. Doctor clean report
    doctor_res = run_doctor_check()
    assert doctor_res["catalog_sqlite_exists"] is True
    assert doctor_res["catalog_sqlite_healthy"] is True
    assert len(doctor_res["missing_artifacts"]) == 0
    assert len(doctor_res["stale_building_releases"]) == 0
    assert len(doctor_res["orphaned_releases"]) == 0
    assert len(doctor_res["catalog_release_missing_on_disk"]) == 0
    assert len(doctor_res["disk_release_missing_in_catalog"]) == 0
