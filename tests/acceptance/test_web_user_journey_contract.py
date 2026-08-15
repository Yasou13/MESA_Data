from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.web.app import create_app
from mesa_legal_data.web.bootstrap import prepare_web_runtime


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "web_contract_data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.delenv("MESA_DATA_WEB_ADMIN_TOKEN", raising=False)
    prepare_web_runtime(custom_data_root=data_root)

    app = create_app()
    with TestClient(app, headers={"X-MESA-Requested-With": "web-admin"}) as test_client:
        yield test_client


def test_harvest_status_initial(client):
    res = client.get("/api/harvest/status")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["state"] == "not_started"
    assert data["source_id"] == "resmi_gazete"
    assert data["coverage_percent"] == 0
    assert data["total_items"] == 0


def test_harvest_start_validation_and_duplicate_guard(client):
    # 1. Unsupported source rejection
    bad_res = client.post("/api/harvest/start", json={"source_id": "mevzuat"})
    assert bad_res.status_code == 400
    assert bad_res.json()["error"]["code"] == "SOURCE_NOT_SUPPORTED"

    # 2. Invalid date rejection
    future_res = client.post("/api/harvest/start", json={"source_id": "resmi_gazete", "start_date": "2099-01-01"})
    assert future_res.status_code == 400
    assert future_res.json()["error"]["code"] == "INVALID_START_DATE"

    # 3. Invalid document types rejection
    bad_types_res = client.post(
        "/api/harvest/start", json={"source_id": "resmi_gazete", "document_types": ["invalid_type"]}
    )
    assert bad_types_res.status_code == 400
    assert bad_types_res.json()["error"]["code"] == "INVALID_DOCUMENT_TYPES"

    # 4. Valid start
    start_res = client.post("/api/harvest/start", json={"source_id": "resmi_gazete", "start_date": "2024-01-01"})
    assert start_res.status_code == 200
    assert start_res.json()["data"]["status"] == "submitted"

    # 5. Duplicate start returns 409
    dup_res = client.post("/api/harvest/start", json={"source_id": "resmi_gazete"})
    assert dup_res.status_code == 409
    assert dup_res.json()["error"]["code"] == "HARVEST_ALREADY_RUNNING"

    # 6. Stop harvest
    stop_res = client.post("/api/harvest/stop")
    assert stop_res.status_code == 200

    # 7. Idempotent second stop
    stop_res2 = client.post("/api/harvest/stop")
    assert stop_res2.status_code == 200
    assert stop_res2.json()["data"]["status"] == "not_running"


def test_sources_truth_table(client):
    res = client.get("/api/sources")
    assert res.status_code == 200
    data = res.json()["data"]
    assert isinstance(data, list)

    sources_by_id = {s["source_id"]: s for s in data}
    assert "resmi_gazete" in sources_by_id
    assert sources_by_id["resmi_gazete"]["automation"] == "supported"

    assert "mevzuat" in sources_by_id
    assert sources_by_id["mevzuat"]["automation"] == "manual"

    assert "aym" in sources_by_id
    assert sources_by_id["aym"]["automation"] == "manual"


def test_exports_list_and_create(client):
    # List initially empty
    res = client.get("/api/exports")
    assert res.status_code == 200
    assert isinstance(res.json()["data"], list)

    # Create export
    c_res = client.post("/api/exports", json={"export_type": "records_jsonl"})
    assert c_res.status_code == 200
    exp_data = c_res.json()["data"]
    assert "export_id" in exp_data

    # List now has 1
    res2 = client.get("/api/exports")
    assert res2.status_code == 200
    assert len(res2.json()["data"]) == 1
    assert res2.json()["data"][0]["export_id"] == exp_data["export_id"]


def test_audit_events_endpoint(client):
    res = client.get("/api/audit-events?limit=50")
    assert res.status_code == 200
    assert isinstance(res.json()["data"], list)


def test_documents_and_reviews_contracts(client):
    # Documents contract
    doc_res = client.get("/api/documents?page=1&page_size=20")
    assert doc_res.status_code == 200
    d_data = doc_res.json()["data"]
    assert "items" in d_data
    assert "total" in d_data
    assert "page" in d_data
    assert "page_size" in d_data

    # Reviews contract
    rev_res = client.get("/api/records?page=1&page_size=20")
    assert rev_res.status_code == 200
    r_data = rev_res.json()["data"]
    assert "items" in r_data
    assert "total" in r_data
    assert "page" in r_data
    assert "page_size" in r_data


def test_regression_mux_cert_001_mesa_transfer_route(client, tmp_path, monkeypatch):
    """Regression test for MUX-CERT-001:

    Verifies that POST /api/releases/{release_id}/import-staging exists,
    preserves release verification checks, and successfully imports published releases.
    """
    import hashlib

    from mesa_legal_data.catalog import (
        approve_version_streaming,
        get_connection,
        insert_artifact,
        upsert_document,
    )
    from mesa_legal_data.pipeline import process_artifact_pipeline

    staging_db = tmp_path / "test_staging.sqlite"
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(staging_db))

    # 1. Non-existent release returns 404
    non_existent = client.post("/api/releases/rel-non-existent/import-staging")
    assert non_existent.status_code == 404
    assert non_existent.json()["error"]["code"] == "RELEASE_NOT_FOUND"

    # Seed an approved record so release build succeeds
    data_root = Path(tmp_path / "web_contract_data")
    raw_dir = data_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "law4721.html"
    html_content = "<!DOCTYPE html><html><body><h1>KANUN</h1><p>No: 4721</p><div><b>Madde 1-</b> Kanun uygulanir.</div></body></html>"
    raw_file.write_text(html_content, encoding="utf-8")
    sha = hashlib.sha256(html_content.encode("utf-8")).hexdigest()
    art_id = f"sha256:{sha}"
    doc_id = "tr:legislation:law:4721"

    conn = get_connection()
    upsert_document(conn, doc_id, "legislation", "law", "TR", "Türk Medeni Kanunu", "4721", "fetched")
    insert_artifact(
        conn,
        artifact_id=art_id,
        document_id=doc_id,
        source_id="resmi_gazete",
        source_url="https://www.resmigazete.gov.tr/eskiler/2026/08/4721.htm",
        retrieved_at="2026-08-01T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_file.stat().st_size,
        sha256=sha,
        raw_path=str(raw_file.relative_to(data_root)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    process_artifact_pipeline(artifact_id=art_id)

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM records LIMIT 1")
    v_id = c.fetchone()[0]
    approve_version_streaming(conn, version_id=v_id, reviewer="web-user", note="Approved")
    conn.close()

    # 2. Build release
    rel_id = "rel-reg-001"
    b_res = client.post("/api/releases", json={"release_id": rel_id})
    assert b_res.status_code == 200

    # 3. Verify release
    v_res = client.post(f"/api/releases/{rel_id}/verify")
    assert v_res.status_code == 200

    # 4. Attempting import on unverified/unpublished release must be rejected with 409
    unpub_res = client.post(f"/api/releases/{rel_id}/import-staging")
    assert unpub_res.status_code == 409
    assert unpub_res.json()["error"]["code"] == "RELEASE_NOT_PUBLISHED"

    # 5. Publish release
    p_res = client.post(f"/api/releases/{rel_id}/publish")
    assert p_res.status_code == 200

    # 6. Import release via frontend route /import-staging succeeds
    imp_res = client.post(f"/api/releases/{rel_id}/import-staging")
    assert imp_res.status_code == 200
    assert imp_res.json()["data"]["status"] == "imported"


def test_regression_mux_cert_002_manual_url_import_route(client):
    """Regression test for MUX-CERT-002:

    Verifies that POST /api/documents/import-url route exists (no 404/405)
    and enforces URL / host security validation.
    """
    # 1. Disallowed external domain is rejected safely with 400
    disallowed_res = client.post(
        "/api/documents/import-url",
        json={
            "source_id": "mevzuat",
            "url": "https://malicious-external-site.com/doc.pdf",
            "document_id": "tr:legislation:law:999",
            "document_type": "law",
        },
    )
    assert disallowed_res.status_code == 400
    assert disallowed_res.json()["error"]["code"] == "URL_IMPORT_FAILED"

    # 2. Allowed domain format check (does not return 404 or 405)
    allowed_host_res = client.post(
        "/api/documents/import-url",
        json={
            "source_id": "mevzuat",
            "url": "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4721.pdf",
            "document_id": "tr:legislation:law:4721",
            "document_type": "law",
        },
    )
    # Status code is not 404 or 405 (route is wired to handler)
    assert allowed_host_res.status_code in (200, 400)


def test_regression_mux_cert_003_harvest_document_type_filtering(client):
    """Regression test for MUX-CERT-003:

    Verifies that harvest document_types passed in start request are properly
    applied to src_cfg.selection.allowed_document_types in operations runner.
    """
    import json
    from unittest.mock import MagicMock, patch

    from mesa_legal_data.catalog import create_operation_job, get_connection
    from mesa_legal_data.operations import _run_operation_task

    conn = get_connection()
    job_id = "op_test_doc_types"
    selected_types = ["law", "regulation"]
    inp = {
        "source_id": "resmi_gazete",
        "start_date": "2024-01-01",
        "document_types": selected_types,
    }
    create_operation_job(
        conn,
        operation_type="harvest_collection",
        requested_by="web-admin",
        input_json=json.dumps(inp),
        operation_id=job_id,
    )
    conn.close()

    mock_run_collection = MagicMock(return_value={"status": "completed", "processed": 5})

    with patch("mesa_legal_data.harvest.service.run_collection_until_pause", mock_run_collection):
        _run_operation_task(job_id)

    assert mock_run_collection.called
    call_kwargs = mock_run_collection.call_args.kwargs
    harvest_cfg = call_kwargs["harvest_cfg"]
    src_cfg = harvest_cfg.sources["resmi_gazete"]

    # Verify that selection.allowed_document_types is exactly the selected subset
    assert src_cfg.selection.allowed_document_types == selected_types
    assert "presidential_decree" not in src_cfg.selection.allowed_document_types


def test_frontend_api_contract_guard():
    """Contract guard verifying all critical endpoints called by app.js exist."""
    from mesa_legal_data.web.api import router

    registered_routes = {
        (route.path, method) for route in router.routes if hasattr(route, "methods") for method in route.methods
    }

    critical_frontend_routes = [
        ("/api/harvest/status", "GET"),
        ("/api/harvest/start", "POST"),
        ("/api/harvest/stop", "POST"),
        ("/api/documents/import-url", "POST"),
        ("/api/artifacts/upload", "POST"),
        ("/api/artifacts/{artifact_id}/process", "POST"),
        ("/api/documents", "GET"),
        ("/api/records", "GET"),
        ("/api/sources", "GET"),
        ("/api/exports", "GET"),
        ("/api/exports", "POST"),
        ("/api/releases", "GET"),
        ("/api/releases", "POST"),
        ("/api/releases/{release_id}/verify", "POST"),
        ("/api/releases/{release_id}/publish", "POST"),
        ("/api/releases/{release_id:path}/import-staging", "POST"),
        ("/api/audit-events", "GET"),
    ]

    for path, method in critical_frontend_routes:
        assert (path, method) in registered_routes, f"Missing route contract: {method} {path}"
