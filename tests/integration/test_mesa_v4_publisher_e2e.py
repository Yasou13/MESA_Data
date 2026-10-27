import hashlib
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
    monkeypatch.setenv("MESA_DATA_MESA_ALLOWED_HOST", "mock-mesa.internal")

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
        contract_source="configured",
        health_path="/health",
        session_start_path="/v4/sessions/start",
        publish_path="/v4/memory/insert",
        mutation_status_path_template="/v4/mutations/{mutation_id}",
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

    # Write canonical file with one authoritative document record and 2 articles.
    c_rel_path = "canonical/legislation/5237.jsonl"
    c_abs_path = data_root / c_rel_path
    c_abs_path.parent.mkdir(parents=True, exist_ok=True)
    article_1 = "MADDE 1- Ceza kanununun amacı adaleti sağlamaktır."
    article_2 = "MADDE 2- Kanunsuz suç olmaz."
    full_text = f"{article_1}\n\n{article_2}"
    records = [
        {"id": doc_id, "record_type": "legislation", "full_text": full_text},
        {
            "id": "art-1",
            "record_type": "article",
            "article_number": "1",
            "heading": "Madde 1",
            "text": article_1,
            "source_span": {"char_start": 0, "char_end": len(article_1)},
        },
        {
            "id": "art-2",
            "record_type": "article",
            "article_number": "2",
            "heading": "Madde 2",
            "text": article_2,
            "source_span": {"char_start": len(article_1) + 2, "char_end": len(full_text)},
        },
    ]
    lines = [json.dumps(record, sort_keys=True) + "\n" for record in records]
    with open(c_abs_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    hashes = [hashlib.sha256(line.encode()).hexdigest() for line in lines]

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
        canonical_sha256=hashes[0],
        parser_name="legislation_parser",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="valid",
        privacy_status="clean",
        approval_status="approved",
        revision_number=1,
        quality_status="PASS",
    )
    conn.execute("UPDATE documents SET current_version_id = ? WHERE document_id = ?", (v_id, doc_id))

    for line_number, record in enumerate(records, start=1):
        insert_record(
            conn=conn,
            record_id=record["id"],
            version_id=v_id,
            record_type=record["record_type"],
            canonical_path=c_rel_path,
            canonical_line=line_number,
            record_sha256=hashes[line_number - 1],
            validation_status="valid",
            approval_status="approved",
        )

    conn.close()
    return db_path


@respx.mock
def test_full_delivery_success_and_cross_release_dedup(setup_publisher_env):
    # Mock MESA endpoints
    respx.get("https://mock-mesa.internal/health").respond(200, json={"status": "ok"})
    starts = respx.post("https://mock-mesa.internal/v4/sessions/start").respond(
        201, json={"status": "started", "session_id": "sess-run-1"}
    )
    inserts = respx.post("https://mock-mesa.internal/v4/memory/insert").respond(
        202, json={"mutation_id": "mut-101", "status": "accepted"}
    )
    respx.get("https://mock-mesa.internal/v4/mutations/mut-101").respond(
        200, json={"mutation_id": "mut-101", "candidate_id": "cand", "state": "COMMITTED"}
    )
    respx.post("https://mock-mesa.internal/v4/sessions/sess-run-1/end").respond(200, json={"status": "ended"})

    # First delivery
    del1 = execute_publish_delivery(delivery_id="del-run-1")
    assert del1["status"] == "COMMITTED"
    assert del1["committed_items"] == 2
    assert del1["skipped_items"] == 0
    assert del1["failed_items"] == 0
    assert starts.call_count == 1
    assert inserts.call_count == 2

    # Second delivery (Cross-release dedup check: same content must be SKIPPED)
    del2 = execute_publish_delivery(delivery_id="del-run-2")
    assert del2["status"] == "COMMITTED"
    assert del2["committed_items"] == 0
    assert del2["skipped_items"] == 2
    assert del2["failed_items"] == 0


@respx.mock
def test_partial_failure_and_retry_workflow(setup_publisher_env):
    respx.get("https://mock-mesa.internal/health").respond(200, json={"status": "ok"})
    respx.post("https://mock-mesa.internal/v4/sessions/start").respond(
        201, json={"status": "started", "session_id": "sess-partial"}
    )

    # First call succeeds for chunk 1, fails for chunk 2
    call_count = 0

    def chunk_handler(request):
        nonlocal call_count
        call_count += 1
        payload = json.loads(request.content)
        if payload.get("chunk_ordinal") == 1:
            return httpx.Response(202, json={"mutation_id": "mut-1", "status": "accepted"})
        else:
            return httpx.Response(500, text="Internal server error")

    respx.post("https://mock-mesa.internal/v4/memory/insert").mock(side_effect=chunk_handler)
    respx.get("https://mock-mesa.internal/v4/mutations/mut-1").respond(
        200, json={"mutation_id": "mut-1", "candidate_id": "cand", "state": "COMMITTED"}
    )

    # 1. Delivery results in PARTIAL
    del_res = execute_publish_delivery(delivery_id="del-partial-1")
    assert del_res["status"] == "PARTIAL"
    assert del_res["committed_items"] == 1
    assert del_res["failed_items"] == 1

    # 2. Fix the server for retry
    respx.post("https://mock-mesa.internal/v4/memory/insert").mock(
        return_value=httpx.Response(202, json={"mutation_id": "mut-2", "status": "accepted"})
    )
    respx.get("https://mock-mesa.internal/v4/mutations/mut-2").respond(
        200, json={"mutation_id": "mut-2", "candidate_id": "cand", "state": "COMMITTED"}
    )
    respx.post("https://mock-mesa.internal/v4/sessions/sess-partial/end").respond(200, json={"status": "ended"})

    # 3. Retry only failed items
    retry_res = retry_delivery_failures(delivery_id="del-partial-1")
    assert retry_res["status"] == "COMMITTED"
    assert retry_res["retried_count"] == 1
    assert retry_res["retried_success"] == 1
    assert retry_res["retried_failed"] == 0


@respx.mock
def test_response_loss_retry_reuses_exact_idempotency_key(setup_publisher_env):
    respx.get("https://mock-mesa.internal/health").respond(200, json={"status": "ok"})
    respx.post("https://mock-mesa.internal/v4/sessions/start").respond(
        201, json={"status": "started", "session_id": "sess-loss"}
    )
    seen_keys = []
    call_count = 0

    def response_loss_then_commit(request):
        nonlocal call_count
        call_count += 1
        seen_keys.append(json.loads(request.content)["idempotency_key"])
        if call_count == 1:
            raise httpx.ReadTimeout("response lost after request was sent", request=request)
        return httpx.Response(202, json={"mutation_id": "mut-after-loss", "status": "accepted"})

    respx.post("https://mock-mesa.internal/v4/memory/insert").mock(side_effect=response_loss_then_commit)
    respx.get("https://mock-mesa.internal/v4/mutations/mut-after-loss").respond(
        200, json={"mutation_id": "mut-after-loss", "candidate_id": "cand", "state": "COMMITTED"}
    )
    respx.post("https://mock-mesa.internal/v4/sessions/sess-loss/end").respond(200, json={"status": "ended"})

    first = execute_publish_delivery(delivery_id="del-response-loss")
    assert first["status"] == "PARTIAL"
    assert first["failed_items"] == 1

    retried = retry_delivery_failures("del-response-loss")
    assert retried["status"] == "COMMITTED"
    assert retried["retried_count"] == 1
    assert len(seen_keys) == 3
    assert seen_keys[0] == seen_keys[2]


@pytest.fixture
def cli_verified_release(tmp_path, monkeypatch):
    from mesa_legal_data.catalog import approve_version_with_checks, get_release, get_version_for_artifact
    from mesa_legal_data.pipeline import process_artifact_pipeline
    from mesa_legal_data.publisher.engine import target_config_sha256
    from mesa_legal_data.release.builder import build_release
    from mesa_legal_data.release.verifier import verify_release
    from mesa_legal_data.sources.manual import import_manual_file

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "test-secret")
    migrate()
    source = tmp_path / "tbk.html"
    source.write_text(
        "<!DOCTYPE html><html><body><h1>6098 TÜRK BORÇLAR KANUNU</h1>"
        "<p>MADDE 1- Sözleşme, tarafların iradelerini karşılıklı ve birbirine uygun olarak açıklamalarıyla kurulur.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    artifact = import_manual_file(
        source,
        source_id="mevzuat",
        document_id="tr:legislation:law:6098",
        extra_metadata={"snapshot_date": "2026-10-27"},
    )
    process_artifact_pipeline(artifact.artifact_id)
    conn = get_connection()
    version = get_version_for_artifact(conn, artifact.artifact_id)
    approve_version_with_checks(conn, version["version_id"], reviewer="test-human")
    settings = MesaTargetSettings(base_url="http://127.0.0.1:8000", contract_source="configured")
    upsert_mesa_target_settings(conn, settings)
    conn.close()
    build_release("cli-release")
    assert verify_release("cli-release")
    conn = get_connection()
    release = get_release(conn, "cli-release")
    conn.close()
    return tmp_path, release, target_config_sha256(settings)


@respx.mock
def test_cli_publish_verified_release_and_repeat(cli_verified_release):
    from typer.testing import CliRunner

    from mesa_legal_data.cli import app

    _, release, target_hash = cli_verified_release
    base = "http://127.0.0.1:8000"
    respx.get(base + "/health").respond(200, json={"status": "ok"})
    starts = respx.post(base + "/v4/sessions/start").respond(201, json={"session_id": "cli-session"})
    inserts = respx.post(base + "/v4/memory/insert").respond(
        202, json={"mutation_id": "cli-mutation", "status": "accepted"}
    )
    respx.get(base + "/v4/mutations/cli-mutation").respond(200, json={"state": "COMMITTED"})
    respx.post(base + "/v4/sessions/cli-session/end").respond(200, json={"status": "ended"})
    args = [
        "publish",
        "run",
        "--release-id",
        release["release_id"],
        "--confirm-manifest",
        release["manifest_sha256"],
        "--confirm-target",
        target_hash,
    ]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "COMMITTED" in result.output
    assert inserts.call_count == 2  # Heading preamble and one numbered article.
    payloads = [json.loads(call.request.content) for call in inserts.calls]
    assert [payload["metadata"]["mesa_data_chunk_type"] for payload in payloads] == ["preamble", "article"]
    assert "legal_identity" not in payloads[0]
    assert payloads[1]["legal_identity"] == {"law_id": "6098", "article_id": "1"}
    conn = get_connection()
    delivery_id, status = conn.execute("SELECT delivery_id, status FROM mesa_deliveries").fetchone()
    assert status == "COMMITTED"
    assert delivery_id in result.output
    events = conn.execute(
        "SELECT actor, subject_id, new_sha256, details_json FROM audit_events WHERE action = 'mesa_publish_authorize'"
    ).fetchall()
    assert len(events) == 1
    assert events[0][0] == "cli"
    assert events[0][1:3] == (release["release_id"], release["manifest_sha256"])
    details = json.loads(events[0][3])
    assert details["delivery_id"] == delivery_id
    assert details["target_config_sha256"] == target_hash
    assert details["scope"]["ready_versions"] == 1
    assert conn.execute("SELECT count(*) FROM operation_jobs").fetchone()[0] == 0
    conn.close()
    status_result = runner.invoke(app, ["publish", "status", delivery_id])
    assert status_result.exit_code == 0, status_result.output
    assert "COMMITTED" in status_result.output and delivery_id in status_result.output
    repeated = runner.invoke(app, args)
    assert repeated.exit_code == 0, repeated.output
    assert inserts.call_count == 2
    assert starts.call_count == 1


@pytest.mark.parametrize(
    "scenario, error",
    [
        ("manifest", "RELEASE_CONFIRMATION_MISMATCH"),
        ("target", "TARGET_CONFIRMATION_MISMATCH"),
        ("unverified", "RELEASE_STATUS_INVALID"),
        ("missing_release", "RELEASE_NOT_FOUND"),
        ("missing_confirmation", "Missing option"),
        ("tamper", "File hash mismatch"),
        ("preflight", "PREFLIGHT_FAILED"),
    ],
)
@respx.mock
def test_cli_publish_rejects_before_sending(cli_verified_release, scenario, error):
    from typer.testing import CliRunner

    from mesa_legal_data.cli import app

    root, release, target_hash = cli_verified_release
    manifest = release["manifest_sha256"]
    release_id = release["release_id"]
    if scenario == "manifest":
        manifest = "0" * 64
    elif scenario == "target":
        target_hash = "0" * 64
    elif scenario == "unverified":
        conn = get_connection()
        conn.execute("UPDATE releases SET status = 'preparing' WHERE release_id = ?", (release_id,))
        conn.close()
    elif scenario == "missing_release":
        release_id = "missing-release"
    elif scenario == "tamper":
        (root / "releases" / release_id / "data" / "articles.jsonl").write_text("{}\n")
    respx.get("http://127.0.0.1:8000/health").respond(503 if scenario == "preflight" else 200, json={"status": "ok"})
    args = ["publish", "run", "--release-id", release_id, "--confirm-manifest", manifest]
    if scenario != "missing_confirmation":
        args += ["--confirm-target", target_hash]
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0
    assert error.lower() in result.output.lower(), result.output
    assert not any(call.request.method == "POST" for call in respx.calls)
    conn = get_connection()
    assert conn.execute("SELECT count(*) FROM mesa_deliveries").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM audit_events WHERE action = 'mesa_publish_authorize'").fetchone()[0] == 0
    conn.close()


@respx.mock
def test_cli_publish_exits_nonzero_unless_committed(cli_verified_release):
    from typer.testing import CliRunner

    from mesa_legal_data.cli import app

    _, release, target_hash = cli_verified_release
    base = "http://127.0.0.1:8000"
    respx.get(base + "/health").respond(200, json={"status": "ok"})
    respx.post(base + "/v4/sessions/start").respond(201, json={"session_id": "cli-session"})
    respx.post(base + "/v4/memory/insert").respond(202, json={"mutation_id": "cli-mutation", "status": "accepted"})
    respx.get(base + "/v4/mutations/cli-mutation").respond(200, json={"state": "REJECTED"})
    result = CliRunner().invoke(
        app,
        [
            "publish",
            "run",
            "--release-id",
            release["release_id"],
            "--confirm-manifest",
            release["manifest_sha256"],
            "--confirm-target",
            target_hash,
        ],
    )
    assert result.exit_code != 0
    assert "FAILED" in result.output or "PARTIAL" in result.output, result.output
    conn = get_connection()
    delivery = conn.execute("SELECT delivery_id, status FROM mesa_deliveries").fetchone()
    assert delivery[0] in result.output
    conn.close()
