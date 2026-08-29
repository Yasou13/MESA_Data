import respx

from mesa_legal_data.catalog import get_connection, insert_artifact, insert_version, migrate, upsert_document
from mesa_legal_data.parsers.coverage import compute_parsing_coverage
from mesa_legal_data.publisher.client import MesaClient
from mesa_legal_data.publisher.engine import get_ready_versions_and_content
from mesa_legal_data.publisher.ledger import create_delivery, get_document_mesa_status, insert_delivery_item
from mesa_legal_data.publisher.models import MesaTargetSettings
from mesa_legal_data.quality import evaluate_quality


def _quality(text: str, spans: list[tuple[int, int]]):
    provenance = {"pipeline_run_id": "test-run"}
    source = {"artifact_sha256": "a" * 64}
    records = [{"id": "doc", "record_type": "legislation", "title": "Kanun", "source": source, "provenance": provenance}]
    records.extend(
        {
            "id": f"article-{index}",
            "record_type": "article",
            "ordinal": index,
            "article_number": str(index),
            "text": text[start:end],
            "source_span": {"char_start": start, "char_end": end},
            "source": source,
            "provenance": provenance,
        }
        for index, (start, end) in enumerate(spans, 1)
    )
    return evaluate_quality(
        source_info={"source_id": "resmi_gazete", "source_url": "https://example.test/law"},
        raw_info={"byte_size": 1, "sha256": "a" * 64, "file_exists": True},
        canonical_records=records,
        canonical_text=text,
        coverage=compute_parsing_coverage(text, spans),
    )


def test_legislation_zero_or_anomalous_coverage_cannot_pass():
    text = "Başlık ve açıklama\n" * 200
    assert _quality(text, []).decision != "PASS"

    article = "MADDE 1- Kısa hüküm"
    anomalous = ("Uzun başlangıç metni\n" * 250) + article
    assert _quality(anomalous, [(len(anomalous) - len(article), len(anomalous))]).decision != "PASS"

    healthy = "Önsöz\n\nMADDE 1- Birinci hüküm\n\nMADDE 2- İkinci hüküm\n\nEK CETVEL\nTablo"
    first = healthy.index("MADDE 1")
    second = healthy.index("MADDE 2")
    annex = healthy.index("EK CETVEL")
    assert _quality(healthy, [(first, second - 2), (second, annex - 2)]).decision == "PASS"


@respx.mock
def test_target_authentication_and_allowlist_are_fail_closed(monkeypatch):
    settings = MesaTargetSettings(
        base_url="https://mesa.example.test",
        contract_source="configured",
        health_path="/health",
        publish_path="/publish",
        mutation_status_path_template="/mutations/{mutation_id}",
    )
    client = MesaClient(settings, api_key="not-logged")
    assert client.test_connection()["connected"] is False

    monkeypatch.setenv("MESA_DATA_MESA_ALLOWED_HOST", "mesa.example.test")
    respx.get("https://mesa.example.test/health").respond(401)
    result = client.test_connection()
    assert result["reachable"] is True
    assert result["authenticated"] is False
    assert result["connected"] is False


def test_only_current_version_is_publishable(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    migrate(None, db_path)
    conn = get_connection(db_path)
    doc_id = "doc-current"
    upsert_document(conn, doc_id, "legislation", "law", "TR", "Kanun", "current", "fetched")
    for version_id, revision, approval, quality in (("v1", 1, "approved", "PASS"), ("v2", 2, "pending", "REVIEW")):
        artifact_id = f"art-{version_id}"
        insert_artifact(
            conn, artifact_id, doc_id, "resmi_gazete", "https://example.test/law", "2026-08-10T00:00:00Z",
            "http", 200, "text/html", "text/html", 1, ("a" if version_id == "v1" else "b") * 64,
            f"raw/{version_id}.html", None, None,
            "verified", None, "{}",
        )
        insert_version(
            conn, version_id, doc_id, artifact_id, "original_publication", "2026-08-10", None, None,
            "canonical/law.jsonl", 1, "a" * 64, "legislation_parser", "1.0.0", "1.0.0", "valid",
            "clean", approval, revision_number=revision, quality_status=quality,
        )
    conn.execute("UPDATE documents SET current_version_id = 'v2' WHERE document_id = ?", (doc_id,))
    ready, blocked = get_ready_versions_and_content(conn)
    assert ready == []
    assert blocked == 0

    create_delivery(conn, delivery_id="old-delivery", release_id=None, target_key="default", total_items=1)
    insert_delivery_item(
        conn, item_id="old-item", delivery_id="old-delivery", document_id=doc_id, version_id="v1",
        chunk_id="chunk-1", content_hash="content", idempotency_key="stable", remote_state="COMMITTED", payload_json="{}",
    )
    assert get_document_mesa_status(conn, doc_id)["status"] == "Update Pending"
    conn.close()
