import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    insert_artifact,
    insert_record,
    insert_version,
    migrate,
    upsert_document,
)
from mesa_legal_data.web.app import create_app


@pytest.fixture
def test_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(tmp_path / "mesa_staging.sqlite"))

    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app()
    client = TestClient(app)
    return client


def test_dashboard_health_metrics_and_mesa_status(test_client):
    res = test_client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()["data"]

    assert "health" in data
    health = data["health"]
    assert "discovered_today" in health
    assert "processed_today" in health
    assert "auto_approved_today" in health
    assert "needs_review_count" in health
    assert "blocked_count" in health
    assert "mesa_ready_count" in health
    assert health["mesa_status"] == "not_configured"
    assert "MESA entegrasyonu yapılandırılmadı" in health["mesa_status_label"]


def test_sources_settings_and_certifications_endpoints(test_client):
    headers = {"X-MESA-Requested-With": "web-admin"}

    # 1. Get initial settings
    res = test_client.get("/api/sources/settings")
    assert res.status_code == 200
    settings = res.json()["data"]
    assert isinstance(settings, list)
    assert any(s["source_id"] == "resmi_gazete" for s in settings)

    # 2. Update operational settings
    update_payload = {
        "enabled": True,
        "auto_approval_enabled": True,
        "weekly_sample_count": 25,
    }
    res_post = test_client.post("/api/sources/resmi_gazete/settings", json=update_payload, headers=headers)
    assert res_post.status_code == 200
    updated = res_post.json()["data"]
    assert updated["source_id"] == "resmi_gazete"
    assert updated["auto_approval_enabled"] is True
    assert updated["weekly_sample_count"] == 25

    # 3. Update parser certification
    cert_payload = {
        "parser_name": "resmi_gazete_parser",
        "parser_version": "1.0.0",
        "certified": True,
        "certified_by": "qa-lead",
    }
    res_cert = test_client.post("/api/sources/resmi_gazete/certify-parser", json=cert_payload, headers=headers)
    assert res_cert.status_code == 200
    certs = res_cert.json()["data"]
    assert any(
        c["parser_name"] == "resmi_gazete_parser" and c["parser_version"] == "1.0.0" and c["certified"] for c in certs
    )


def test_document_versions_and_pending_reviews_endpoint(test_client):
    headers = {"X-MESA-Requested-With": "web-admin"}
    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:5237", "legislation", "law", "TR", "TCK", "5237", "fetched")

    insert_artifact(
        conn=conn,
        artifact_id="art-tck-1",
        document_id="tr:legislation:law:5237",
        source_id="resmi_gazete",
        source_url="https://resmigazete.gov.tr/5237.html",
        retrieved_at="2026-08-28T12:00:00Z",
        fetch_method="http",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=1024,
        sha256="1111222233334444555566667777888899990000111122223333444455556666",
        raw_path="raw/resmi_gazete/5237.html",
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )

    canonical_path = "canonical/test.jsonl"
    canonical_line = json.dumps({"id": "tck-rec-1", "record_type": "article"}, sort_keys=True) + "\n"
    canonical_abs = Path(os.environ["MESA_DATA_DATA_ROOT"]) / canonical_path
    canonical_abs.parent.mkdir(parents=True, exist_ok=True)
    canonical_abs.write_text(canonical_line, encoding="utf-8")
    canonical_hash = hashlib.sha256(canonical_line.encode()).hexdigest()

    insert_version(
        conn=conn,
        version_id="tr:legislation:law:5237:v1",
        document_id="tr:legislation:law:5237",
        artifact_id="art-tck-1",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path=canonical_path,
        canonical_line=1,
        canonical_sha256=canonical_hash,
        parser_name="resmi_gazete_parser",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="valid",
        privacy_status="clean",
        approval_status="pending",
        revision_number=1,
        quality_status="REVIEW",
        quality_json=json.dumps({"checks": [{"name": "STRUCTURE", "status": "REVIEW"}]}),
    )
    insert_record(
        conn,
        "tck-rec-1",
        "tr:legislation:law:5237:v1",
        "article",
        canonical_path,
        1,
        canonical_hash,
    )
    conn.close()

    # 1. Query document versions
    res_ver = test_client.get("/api/documents/tr:legislation:law:5237/versions")
    assert res_ver.status_code == 200
    versions = res_ver.json()["data"]["versions"]
    assert len(versions) == 1
    assert versions[0]["version_id"] == "tr:legislation:law:5237:v1"
    assert versions[0]["revision_number"] == 1
    assert versions[0]["quality_status"] == "REVIEW"

    # 2. Query pending versions review queue
    res_pending = test_client.get("/api/reviews/pending-versions")
    assert res_pending.status_code == 200
    pending_items = res_pending.json()["data"]["items"]
    assert len(pending_items) >= 1
    assert any(item["version_id"] == "tr:legislation:law:5237:v1" for item in pending_items)

    # 3. Approve version
    res_app = test_client.post(
        "/api/versions/tr:legislation:law:5237:v1/approve",
        json={"reviewer": "test-admin", "note": "Verified manually"},
        headers=headers,
    )
    assert res_app.status_code == 200
    assert res_app.json()["ok"] is True
