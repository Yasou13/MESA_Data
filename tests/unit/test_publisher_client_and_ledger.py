import json

import pytest
import respx

from mesa_legal_data.catalog import get_connection, migrate
from mesa_legal_data.publisher.client import MesaClient
from mesa_legal_data.publisher.ledger import (
    create_delivery,
    get_delivery,
    get_document_mesa_status,
    get_mesa_target_settings,
    insert_delivery_item,
    is_chunk_already_committed,
    list_failed_delivery_items,
    set_delivery_remote_session,
    update_delivery_progress,
    upsert_mesa_target_settings,
)
from mesa_legal_data.publisher.models import MesaTargetSettings, MutationState, SourceChunk


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test_catalog.sqlite"
    migrate(None, db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


def test_target_settings_persistence(db_conn):
    settings = MesaTargetSettings(
        target_key="default",
        base_url="https://mesa.example.org",
        tenant_id="enterprise",
        workspace_id="legal_corp",
        dataset_id="turkey_laws",
        agent_id="agent_mesa_01",
        content_limit_chars=16384,
    )
    upsert_mesa_target_settings(db_conn, settings)

    loaded = get_mesa_target_settings(db_conn, "default")
    assert loaded.base_url == "https://mesa.example.org"
    assert loaded.tenant_id == "enterprise"
    assert loaded.workspace_id == "legal_corp"
    assert loaded.dataset_id == "turkey_laws"
    assert loaded.agent_id == "agent_mesa_01"
    assert loaded.content_limit_chars == 16384
    assert loaded.session_start_path == "/v4/sessions/start"
    assert loaded.session_end_path_template == "/v4/sessions/{session_id}/end"


def test_api_key_secrecy_and_isolation(monkeypatch):
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "secret_token_12345")
    settings = MesaTargetSettings(target_key="default", base_url="http://localhost:8000")
    client = MesaClient(settings=settings)

    assert client.is_api_key_configured is True
    # MESA bootstrap API keys use the exact X-API-Key contract, never Bearer.
    headers = client._get_headers()
    assert headers["X-API-Key"] == "secret_token_12345"
    assert "Authorization" not in headers

    # Verify settings dump does NOT leak the API key
    dumped = settings.model_dump()
    assert "secret_token_12345" not in str(dumped)


@respx.mock
@pytest.mark.parametrize("response_json", [{}, {"state": "unknown_future_state"}, {"status": "accepted"}])
def test_committed_truth_requires_explicit_committed(response_json):
    settings = MesaTargetSettings(
        base_url="https://mesa-contract.test",
        contract_source="configured",
        health_path="/health-contract",
        publish_path="/publish-contract",
        mutation_status_path_template="/mutations-contract/{mutation_id}",
    )
    client = MesaClient(settings=settings, api_key="secret")
    chunk = SourceChunk(
        chunk_id="v1:chunk:1",
        document_id="doc-1",
        version_id="v1",
        chunk_type="general",
        char_start=0,
        char_end=4,
        ordinal=1,
        content="test",
        content_hash="hash",
    )
    respx.post("https://mesa-contract.test/publish-contract").respond(200, json=response_json)

    result = client.publish_source_chunk(chunk, "stable-key", session_id="session-1", finalize_revision=True)

    assert result["state"] != MutationState.COMMITTED.value


@respx.mock
def test_native_v4_session_and_insert_payload_are_exact(monkeypatch):
    monkeypatch.setenv("MESA_DATA_MESA_ALLOWED_HOST", "mesa-contract.test")
    settings = MesaTargetSettings(base_url="https://mesa-contract.test", contract_source="configured")
    client = MesaClient(settings=settings, api_key="secret")
    chunk = SourceChunk(
        chunk_id="v1:chunk:3",
        document_id="doc-1",
        version_id="v1",
        chunk_type="article",
        title="Madde 3",
        char_start=10,
        char_end=22,
        ordinal=3,
        content="canonical text",
        content_hash="content-hash",
        metadata={"revision_number": 2, "source_url": "https://authority.test/doc-1"},
    )
    start = respx.post("https://mesa-contract.test/v4/sessions/start").respond(
        201, json={"status": "started", "session_id": "sess-1"}
    )

    def assert_insert(request):
        assert request.headers["X-API-Key"] == "secret"
        assert "Authorization" not in request.headers
        assert "Idempotency-Key" not in request.headers
        payload = json.loads(request.content)
        assert payload == {
            "session_id": "sess-1",
            "dataset_id": "tr_legislation",
            "document_id": "doc-1",
            "revision_id": "v1",
            "chunk_id": "v1:chunk:3",
            "title": "Madde 3",
            "source_ref": "https://authority.test/doc-1",
            "content": "canonical text",
            "evidence_span": "",
            "revision_number": 2,
            "chunk_ordinal": 3,
            "finalize_revision": True,
            "supersedes_revision_id": None,
            "metadata": {
                "revision_number": 2,
                "source_url": "https://authority.test/doc-1",
                "mesa_data_chunk_type": "article",
                "mesa_data_char_start": 10,
                "mesa_data_char_end": 22,
                "mesa_data_content_hash": "content-hash",
            },
            "idempotency_key": "stable-key",
        }
        return httpx.Response(202, json={"status": "accepted", "mutation_id": "mut-1"})

    import httpx

    insert = respx.post("https://mesa-contract.test/v4/memory/insert").mock(side_effect=assert_insert)
    assert client.start_session()["session_id"] == "sess-1"
    result = client.publish_source_chunk(chunk, "stable-key", session_id="sess-1", finalize_revision=True)
    assert result["state"] == MutationState.QUEUED.value
    assert start.called and insert.called


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ACCEPTED", "QUEUED"),
        ("RECEIVED", "QUEUED"),
        ("EXTRACTED", "PROCESSING"),
        ("VALIDATED", "PROCESSING"),
        ("SQL_APPLIED", "PROCESSING"),
        ("VECTOR_APPLIED", "PROCESSING"),
        ("GRAPH_APPLIED", "PROCESSING"),
        ("RETRY_PENDING", "PROCESSING"),
        ("COMMITTED", "COMMITTED"),
        ("REJECTED", "REJECTED"),
        ("DEAD_LETTER", "FAILED"),
        ("BLOCKED", "FAILED"),
        ("ROLLED_BACK", "FAILED"),
        ("UNKNOWN_FUTURE_STATE", "FAILED"),
    ],
)
def test_current_mesa_v4_mutation_state_normalization(raw, expected):
    state, _ = MesaClient._normalize_mutation_state(raw)
    assert state == expected


def test_multi_chunk_revision_finalizes_only_last_chunk():
    client = MesaClient(MesaTargetSettings(), api_key="secret")
    chunks = [
        SourceChunk(
            chunk_id=f"v1:chunk:{ordinal}",
            document_id="doc-1",
            version_id="v1",
            chunk_type="general",
            char_start=ordinal,
            char_end=ordinal + 1,
            ordinal=ordinal,
            content=f"chunk {ordinal}",
            content_hash=f"hash-{ordinal}",
        )
        for ordinal in (1, 2, 3)
    ]
    payloads = [
        client.build_memory_insert_payload(
            chunk,
            session_id="sess-1",
            idempotency_key=f"key-{chunk.ordinal}",
            finalize_revision=chunk.ordinal == 3,
        )
        for chunk in chunks
    ]
    assert [payload["finalize_revision"] for payload in payloads] == [False, False, True]


def test_unknown_contract_never_guesses_routes():
    client = MesaClient(settings=MesaTargetSettings(base_url="https://mesa-contract.test"), api_key="secret")
    assert client.is_contract_configured is False
    assert client.test_connection()["connected"] is False


def test_delivery_ledger_and_cross_release_dedup(db_conn):
    delivery_id = "del-test-01"
    create_delivery(db_conn, delivery_id=delivery_id, release_id="rel-1", target_key="default", total_items=2)
    set_delivery_remote_session(db_conn, delivery_id=delivery_id, remote_session_id="sess-persisted")

    insert_delivery_item(
        db_conn,
        item_id="item-01",
        delivery_id=delivery_id,
        document_id="doc-1",
        version_id="doc-1:v1",
        chunk_id="chunk-01",
        content_hash="sha-content-1",
        idempotency_key="mesa-data:key1",
        remote_state=MutationState.COMMITTED.value,
        payload_json="{}",
    )

    insert_delivery_item(
        db_conn,
        item_id="item-02",
        delivery_id=delivery_id,
        document_id="doc-1",
        version_id="doc-1:v1",
        chunk_id="chunk-02",
        content_hash="sha-content-2",
        idempotency_key="mesa-data:key2",
        remote_state=MutationState.FAILED.value,
        payload_json="{}",
    )

    update_delivery_progress(
        db_conn,
        delivery_id=delivery_id,
        status="PARTIAL",
        committed_items=1,
        failed_items=1,
        skipped_items=0,
        finished=True,
    )

    del_info = get_delivery(db_conn, delivery_id)
    assert del_info is not None
    assert del_info["status"] == "PARTIAL"
    assert del_info["committed_items"] == 1
    assert del_info["failed_items"] == 1
    assert del_info["remote_session_id"] == "sess-persisted"

    # Cross-release dedup check
    assert (
        is_chunk_already_committed(
            db_conn,
            target_key="default",
            document_id="doc-1",
            version_id="doc-1:v1",
            chunk_id="chunk-01",
            content_hash="sha-content-1",
        )
        is True
    )

    # Modified content hash or failed chunk is NOT committed
    assert (
        is_chunk_already_committed(
            db_conn,
            target_key="default",
            document_id="doc-1",
            version_id="doc-1:v1",
            chunk_id="chunk-01",
            content_hash="sha-content-modified",
        )
        is False
    )

    assert (
        is_chunk_already_committed(
            db_conn,
            target_key="default",
            document_id="doc-1",
            version_id="doc-1:v1",
            chunk_id="chunk-02",
            content_hash="sha-content-2",
        )
        is False
    )

    # Retry failures query
    failed = list_failed_delivery_items(db_conn, delivery_id)
    assert len(failed) == 1
    assert failed[0]["item_id"] == "item-02"

    # No current document version was created for this ledger-only fixture;
    # historical delivery evidence must not be presented as current committed state.
    doc_status = get_document_mesa_status(db_conn, "doc-1")
    assert doc_status["status"] == "Update Pending"
