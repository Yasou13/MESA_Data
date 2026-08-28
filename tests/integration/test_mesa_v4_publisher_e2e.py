import json

import httpx
import pytest
import respx

from mesa_legal_data.catalog import (
    get_connection,
    insert_artifact,
    insert_record,
    insert_version,
    migrate,
    upsert_document,
)
from mesa_legal_data.publisher.engine import execute_publish_delivery, retry_delivery_failures
from mesa_legal_data.publisher.ledger import upsert_mesa_target_settings
from mesa_legal_data.publisher.models import MesaTargetSettings


@pytest.fixture
def setup_publisher_env(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "catalog.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "test_secret_api_key")

    migrate(None, db_path)
    conn = get_connection(db_path)

    # 1. Setup Target Settings
    settings = MesaTargetSettings(
        target_key="default",
        base_url="https://mock-mesa.internal",
        tenant_id="default",
        workspace_id="legal",
        dataset_id="tr_legislation",
        agent_id="publisher",
    )
    upsert_mesa_target_settings(conn, settings)

    # 2. Setup document and approved version
    doc_id = "tr:legislation:law:5237"
    upsert_document(conn, doc_id, "legislation", "law", "TR", "Türk Ceza Kanunu", "stable-5237", "approved")

    insert_artifact(
        conn=conn,
        artifact_id="art-5237-v1",
        document_id=doc_id,
        source_id="resmi_gazete",
        source_url="https://resmigazete.gov.tr/5237.html",
        retrieved_at="2026-01-01T00:00:00Z",
        fetch_method="http",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=1024,
        sha256="1111111111111111111111111111111111111111111111111111111111111111",
        raw_path="raw/resmi_gazete/5237.html",
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )

    # Write canonical file with 2 article records
    c_rel_path = "canonical/legislation/5237.jsonl"
    c_abs_path = data_root / c_rel_path
    c_abs_path.parent.mkdir(parents=True, exist_ok=True)
    with open(c_abs_path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "id": "art-1",
                    "type": "article",
                    "article_number": "1",
                    "title": "Madde 1",
                    "content": "MADDE 1- Ceza kanununun amacı adaleti sağlamaktır.",
                }
            )
            + "\n"
        )
        f.write(
            json.dumps(
                {
                    "id": "art-2",
                    "type": "article",
                    "article_number": "2",
                    "title": "Madde 2",
                    "content": "MADDE 2- Kanunsuz suç olmaz.",
                }
            )
            + "\n"
        )

    v_id = f"{doc_id}:v1"
    insert_version(
        conn=conn,
        version_id=v_id,
        document_id=doc_id,
        artifact_id="art-5237-v1",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path=c_rel_path,
        canonical_line=1,
        canonical_sha256="2222222222222222222222222222222222222222222222222222222222222222",
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
        record_id="art-1",
        version_id=v_id,
        record_type="article",
        canonical_path=c_rel_path,
        canonical_line=1,
        record_sha256="3333333333333333333333333333333333333333333333333333333333333333",
        validation_status="valid",
        approval_status="approved",
    )

    insert_record(
        conn=conn,
        record_id="art-2",
        version_id=v_id,
        record_type="article",
        canonical_path=c_rel_path,
        canonical_line=1,
        record_sha256="4444444444444444444444444444444444444444444444444444444444444444",
        validation_status="valid",
        approval_status="approved",
    )

    conn.close()
    return db_path


@respx.mock
def test_full_delivery_success_and_cross_release_dedup(setup_publisher_env):
    # Mock MESA endpoints
    respx.get("https://mock-mesa.internal/v4/health").respond(200, json={"status": "ok"})
    respx.post("https://mock-mesa.internal/v4/sources/chunks").respond(
        200, json={"mutation_id": "mut-101", "state": "COMMITTED", "message": "Committed directly"}
    )

    # First delivery
    del1 = execute_publish_delivery(delivery_id="del-run-1")
    assert del1["status"] == "COMMITTED"
    assert del1["committed_items"] == 2
    assert del1["skipped_items"] == 0
    assert del1["failed_items"] == 0

    # Second delivery (Cross-release dedup check: same content must be SKIPPED)
    del2 = execute_publish_delivery(delivery_id="del-run-2")
    assert del2["status"] == "COMMITTED"
    assert del2["committed_items"] == 0
    assert del2["skipped_items"] == 2
    assert del2["failed_items"] == 0


@respx.mock
def test_partial_failure_and_retry_workflow(setup_publisher_env):
    respx.get("https://mock-mesa.internal/v4/health").respond(200, json={"status": "ok"})

    # First call succeeds for chunk 1, fails for chunk 2
    call_count = 0

    def chunk_handler(request):
        nonlocal call_count
        call_count += 1
        payload = json.loads(request.content)
        if payload.get("ordinal") == 1:
            return httpx.Response(200, json={"mutation_id": "mut-1", "state": "COMMITTED"})
        else:
            return httpx.Response(500, text="Internal server error")

    respx.post("https://mock-mesa.internal/v4/sources/chunks").mock(side_effect=chunk_handler)

    # 1. Delivery results in PARTIAL
    del_res = execute_publish_delivery(delivery_id="del-partial-1")
    assert del_res["status"] == "PARTIAL"
    assert del_res["committed_items"] == 1
    assert del_res["failed_items"] == 1

    # 2. Fix the server for retry
    respx.post("https://mock-mesa.internal/v4/sources/chunks").mock(
        return_value=httpx.Response(200, json={"mutation_id": "mut-2", "state": "COMMITTED"})
    )

    # 3. Retry only failed items
    retry_res = retry_delivery_failures(delivery_id="del-partial-1")
    assert retry_res["status"] == "COMMITTED"
    assert retry_res["retried_count"] == 1
    assert retry_res["retried_success"] == 1
    assert retry_res["retried_failed"] == 0
