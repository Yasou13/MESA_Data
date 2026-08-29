import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    insert_artifact,
    insert_record,
    insert_version,
    migrate,
    upsert_document,
)
from mesa_legal_data.publisher.ledger import upsert_mesa_target_settings
from mesa_legal_data.publisher.models import MesaTargetSettings
from mesa_legal_data.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "catalog.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "env_secret_key")

    migrate(None, db_path)
    conn = get_connection(db_path)

    upsert_mesa_target_settings(
        conn,
        MesaTargetSettings(
            target_key="default",
            base_url="https://mock-mesa.internal",
            tenant_id="default",
            workspace_id="legal",
            dataset_id="tr_legislation",
            agent_id="publisher",
            contract_source="configured",
            health_path="/v4/health",
            publish_path="/v4/sources/chunks",
            mutation_status_path_template="/v4/mutations/{mutation_id}",
        ),
    )

    doc_id = "tr:legislation:law:6100"
    upsert_document(conn, doc_id, "legislation", "law", "TR", "HMK", "stable-6100", "approved")

    insert_artifact(
        conn=conn,
        artifact_id="art-6100-v1",
        document_id=doc_id,
        source_id="resmi_gazete",
        source_url="https://resmigazete.gov.tr/6100.html",
        retrieved_at="2026-01-01T00:00:00Z",
        fetch_method="http",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=1024,
        sha256="5555555555555555555555555555555555555555555555555555555555555555",
        raw_path="raw/resmi_gazete/6100.html",
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )

    c_rel_path = "canonical/legislation/6100.jsonl"
    c_abs_path = data_root / c_rel_path
    c_abs_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_line = (
        json.dumps(
            {
                "id": doc_id,
                "record_type": "legislation",
                "full_text": "MADDE 1- Görev kamu düzenine ilişkindir.",
            },
            sort_keys=True,
        )
        + "\n"
    )
    c_abs_path.write_text(canonical_line, encoding="utf-8")
    canonical_hash = hashlib.sha256(canonical_line.encode()).hexdigest()

    v_id = f"{doc_id}:v1"
    insert_version(
        conn=conn,
        version_id=v_id,
        document_id=doc_id,
        artifact_id="art-6100-v1",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path=c_rel_path,
        canonical_line=1,
        canonical_sha256=canonical_hash,
        parser_name="legislation_parser",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="valid",
        privacy_status="clean",
        approval_status="approved",
        revision_number=1,
        quality_status="PASS",
    )

    insert_record(
        conn=conn,
        record_id=doc_id,
        version_id=v_id,
        record_type="legislation",
        canonical_path=c_rel_path,
        canonical_line=1,
        record_sha256=canonical_hash,
        validation_status="valid",
        approval_status="approved",
    )
    conn.close()

    app = create_app()
    return TestClient(app)


def test_publisher_settings_and_preflight_endpoints(client):
    headers = {"X-MESA-Requested-With": "web-admin"}

    # 1. GET Settings
    res_get = client.get("/api/publisher/settings", headers=headers)
    assert res_get.status_code == 200
    data = res_get.json()["data"]
    assert data["base_url"] == "https://mock-mesa.internal"
    assert data["api_key_configured"] is True

    # 2. POST Update Settings
    res_post = client.post(
        "/api/publisher/settings",
        headers=headers,
        json={
            "base_url": "https://mesa-updated.internal",
            "tenant_id": "corp",
            "workspace_id": "legal",
            "dataset_id": "tr_legislation",
            "agent_id": "publisher_v4",
            "content_limit_chars": 65536,
            "health_path": "/v4/health",
            "publish_path": "/v4/sources/chunks",
            "mutation_status_path_template": "/v4/mutations/{mutation_id}",
        },
    )
    assert res_post.status_code == 200
    upd_data = res_post.json()["data"]
    assert upd_data["base_url"] == "https://mesa-updated.internal"
    assert upd_data["tenant_id"] == "corp"
    assert upd_data["content_limit_chars"] == 65536

    # 3. GET Ready Summary
    res_sum = client.get("/api/publisher/ready-summary", headers=headers)
    assert res_sum.status_code == 200
    sum_data = res_sum.json()["data"]
    assert sum_data["ready_documents"] >= 1
    assert sum_data["ready_versions"] >= 1

    # 4. GET Document MESA Status
    res_doc_st = client.get("/api/documents/tr:legislation:law:6100/mesa-status", headers=headers)
    assert res_doc_st.status_code == 200
    doc_st = res_doc_st.json()["data"]
    assert doc_st["status"] == "Not Sent"
