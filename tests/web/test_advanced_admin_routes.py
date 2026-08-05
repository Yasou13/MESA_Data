import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    hash_file,
    insert_artifact,
    insert_record,
    insert_version,
    migrate,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app({"data_root": str(tmp_path)})
    c = TestClient(app)
    c.headers.update({"X-MESA-Requested-With": "web-admin"})
    return c


def test_advanced_web_routes_end_to_end(client, tmp_path):
    # Seed source, document, artifact, version
    conn = get_connection()
    upsert_source(conn, "mevzuat", "Mevzuat", "T.C. Cumhurbaşkanlığı", "https://www.mevzuat.gov.tr")
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")

    raw_file = tmp_path / "raw" / "payload.html"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("<html>Raw Payload</html>", encoding="utf-8")

    can_file = tmp_path / "canonical" / "part1.jsonl"
    can_file.parent.mkdir(parents=True, exist_ok=True)
    can_file.write_text('{"record_id": "rec-1"}\n', encoding="utf-8")

    raw_hash = hash_file(raw_file)
    insert_artifact(
        conn,
        "art-1",
        "tr:legislation:law:4721",
        "mevzuat",
        "https://www.mevzuat.gov.tr/4721",
        "2026-08-05T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        raw_file.stat().st_size,
        raw_hash,
        "raw/payload.html",
        None,
        None,
        "fetched",
        None,
        "{}",
    )
    insert_version(
        conn,
        "ver-1",
        "tr:legislation:law:4721",
        "art-1",
        "full",
        None,
        None,
        None,
        "canonical/part1.jsonl",
        1,
        "hashcan",
        "mevzuat",
        "1.0.0",
        "1.0.0",
        "valid",
        "clean",
        "pending",
    )
    insert_record(
        conn,
        "rec-1",
        "ver-1",
        "article",
        "canonical/part1.jsonl",
        1,
        "hashrec",
        "valid",
        "pending",
    )
    conn.close()

    # 1. Download raw
    res_raw = client.get("/api/documents/tr:legislation:law:4721/download/raw")
    assert res_raw.status_code == 200, f"res_raw failed: {res_raw.text}"
    assert "Raw Payload" in res_raw.text

    # 2. Download canonical
    res_can = client.get("/api/documents/tr:legislation:law:4721/download/canonical")
    assert res_can.status_code == 200
    assert "rec-1" in res_can.text

    # 3. Annotations (Removed from public API -> 404/405)
    res_ann = client.post(
        "/api/records/rec-1/annotations",
        json={"annotation_type": "tag", "namespace": "mesa.test", "key": "priority", "value": "high"},
    )
    assert res_ann.status_code in (404, 405)

    res_ann_list = client.get("/api/records/rec-1/annotations")
    assert res_ann_list.status_code in (404, 405)

    # 4. Source Config Revisions (Removed from public API -> 404/405)
    res_cfg = client.post(
        "/api/source-configs/revisions",
        json={"content_yaml": "sources:\n  mevzuat:\n    enabled: true\n", "reason": "Test update"},
    )
    assert res_cfg.status_code in (404, 405)

    # 5. Export Packages
    res_exp = client.post("/api/exports", json={"export_type": "records_jsonl", "filters": {}})
    assert res_exp.status_code == 200
    exp_id = res_exp.json()["data"]["export_id"]

    res_exp_down = client.get(f"/api/exports/{exp_id}/download")
    assert res_exp_down.status_code == 200

    # 6. Operations Jobs
    res_op = client.post("/api/operations/jobs", json={"operation_type": "filtered_export", "input": {}})
    assert res_op.status_code == 200
    op_id = res_op.json()["data"]["operation_id"]

    res_op_get = client.get(f"/api/operations/jobs/{op_id}")
    assert res_op_get.status_code == 200
    assert res_op_get.json()["data"]["status"] in ("queued", "submitted", "running", "succeeded")

    # 7. Audit Events
    res_audit = client.get("/api/audit-events")
    assert res_audit.status_code == 200

    # 8. Document Text Preview
    res_text = client.get("/api/documents/tr:legislation:law:4721/text")
    assert res_text.status_code == 200
    assert "Raw Payload" in res_text.json()["data"]["content"]
