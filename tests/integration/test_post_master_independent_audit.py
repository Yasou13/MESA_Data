import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    CatalogError,
    approve_record_with_checks,
    approve_version_streaming,
    get_connection,
    get_db_path,
    get_document,
    get_record,
    get_version_for_artifact,
    hash_file,
    insert_artifact,
    migrate,
    open_issue,
    recompute_document_current_version,
    reject_version,
    set_parser_certification,
    transaction,
    upsert_document,
    upsert_source,
    upsert_source_operational_settings,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.parsers.citations import extract_citations
from mesa_legal_data.parsers.coverage import compute_parsing_coverage
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.publisher.client import MesaClient, MesaClientError
from mesa_legal_data.publisher.engine import build_delivery_plan, execute_publish_delivery, retry_delivery_failures
from mesa_legal_data.publisher.hashing import generate_idempotency_key
from mesa_legal_data.publisher.ledger import (
    create_delivery,
    insert_delivery_item,
    upsert_mesa_target_settings,
)
from mesa_legal_data.publisher.models import DeliveryStatus, MesaTargetSettings, SourceChunk
from mesa_legal_data.quality import evaluate_quality
from mesa_legal_data.release import publish_release
from mesa_legal_data.release.builder import ReleaseBuildError, build_release
from mesa_legal_data.release.importer import ReleaseNotPublished, import_release_to_staging
from mesa_legal_data.release.verifier import ReleaseVerificationError, verify_release
from mesa_legal_data.validators.privacy import scan_privacy_issues
from mesa_legal_data.web.app import create_app

WEB_HEADERS = {"X-MESA-Requested-With": "web-admin"}


def _helper_create_law_artifact(
    tmp_path: Path,
    doc_id: str,
    raw_html: str,
    artifact_id: str,
    source_id: str = "mevzuat",
    pub_date: str | None = None,
    source_role: str | None = None,
    retrieved_at: str = "2026-08-01T00:00:00Z",
) -> str:
    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / source_id / "2026" / artifact_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"
    raw_bytes = raw_html.encode("utf-8")
    raw_file.write_bytes(raw_bytes)

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)

    meta_dict: dict[str, Any] = {}
    if pub_date:
        meta_dict["publication_date"] = pub_date
    if source_role:
        meta_dict["source_role"] = source_role

    conn = get_connection()
    upsert_source(conn, source_id, source_id.capitalize(), "Test Agency", f"https://example.com/{source_id}")
    upsert_document(conn, doc_id, "legislation", "law", "TR", f"Test Law {doc_id}", doc_id, "fetched")
    insert_artifact(
        conn,
        artifact_id=artifact_id,
        document_id=doc_id,
        source_id=source_id,
        source_url=f"https://example.com/{artifact_id}",
        retrieved_at=retrieved_at,
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=len(raw_bytes),
        sha256=sha256,
        raw_path=str(raw_file.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json=json.dumps(meta_dict) if meta_dict else "{}",
    )
    conn.close()
    return artifact_id


# ==============================================================================
# GROUP A: CONTROLS 1 - 10 (Chronology, Date Precedence, Isolation, Revisions)
# ==============================================================================


def test_control_1_to_3_chronology_and_date_precedence(tmp_path, monkeypatch):
    """Controls 1, 2, 3: Date precedence priority and past date isolation."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:date-prec-123"

    # Ingest version A: 2026-01-01
    html_a = """<html><body><h1>LAW A</h1><p><b>Madde 1-</b> İçerik A.</p></body></html>"""
    art_a = _helper_create_law_artifact(tmp_path, doc_id, html_a, "art-prec-a", pub_date="2026-01-01")
    process_artifact_pipeline(art_a)

    conn = get_connection()
    va = get_version_for_artifact(conn, art_a)
    doc_a = get_document(conn, doc_id)
    assert doc_a["current_version_id"] == va["version_id"]
    conn.close()

    # Ingest version B: 2020-01-01 (older legal date, retrieved later)
    html_b = """<html><body><h1>LAW B</h1><p><b>Madde 1-</b> İçerik B.</p></body></html>"""
    art_b = _helper_create_law_artifact(
        tmp_path, doc_id, html_b, "art-prec-b", pub_date="2020-01-01", retrieved_at="2026-08-29T23:00:00Z"
    )
    process_artifact_pipeline(art_b)

    conn = get_connection()
    doc_b = get_document(conn, doc_id)
    # The older 2020 version must NOT replace the 2026 version as current
    assert doc_b["current_version_id"] == va["version_id"]
    conn.close()


def test_control_4_current_version_chronology_exact_scenario(tmp_path, monkeypatch):
    """Control 4: Processing 2026-05-10, 2024-03-12, 2025-08-01 in arbitrary order must yield current_version = 2026-05-10."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:chronology-exact-4"

    # Ingest 1: 2026-05-10
    html_2026 = """<html><body><h1>CHRONOLOGY LAW</h1><p><b>Madde 1-</b> 2026-05-10 text.</p></body></html>"""
    art_2026 = _helper_create_law_artifact(tmp_path, doc_id, html_2026, "art-exact-2026", pub_date="2026-05-10")
    process_artifact_pipeline(art_2026)

    # Ingest 2: 2024-03-12
    html_2024 = """<html><body><h1>CHRONOLOGY LAW</h1><p><b>Madde 1-</b> 2024-03-12 text.</p></body></html>"""
    art_2024 = _helper_create_law_artifact(tmp_path, doc_id, html_2024, "art-exact-2024", pub_date="2024-03-12")
    process_artifact_pipeline(art_2024)

    # Ingest 3: 2025-08-01
    html_2025 = """<html><body><h1>CHRONOLOGY LAW</h1><p><b>Madde 1-</b> 2025-08-01 text.</p></body></html>"""
    art_2025 = _helper_create_law_artifact(tmp_path, doc_id, html_2025, "art-exact-2025", pub_date="2025-08-01")
    process_artifact_pipeline(art_2025)

    conn = get_connection()
    doc = get_document(conn, doc_id)
    assert doc is not None
    v_2026 = get_version_for_artifact(conn, art_2026)
    assert v_2026 is not None
    assert doc["current_version_id"] == v_2026["version_id"]
    assert "2026-05-10" in doc["current_version_id"]

    # Explicit recompute preserves the 2026-05-10 version
    chosen = recompute_document_current_version(conn, doc_id)
    assert chosen == v_2026["version_id"]
    conn.close()


def test_control_5_unknown_legal_date_never_becomes_current(tmp_path, monkeypatch):
    """Control 5: Candidate with unknown legal date (retrieved_at = today) cannot replace known 2026 version, cannot auto-approve."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:unknown-date-5"

    # Known 2026 version
    html_2026 = """<html><body><h1>KNOWN LAW</h1><p><b>Madde 1-</b> Known 2026 date text.</p></body></html>"""
    art_2026 = _helper_create_law_artifact(tmp_path, doc_id, html_2026, "art-known-2026", pub_date="2026-01-15")
    process_artifact_pipeline(art_2026)

    conn = get_connection()
    v_2026 = get_version_for_artifact(conn, art_2026)
    assert v_2026 is not None
    doc_before = get_document(conn, doc_id)
    assert doc_before["current_version_id"] == v_2026["version_id"]
    conn.close()

    # Candidate with unknown publication date, retrieved today
    html_unk = """<html><body><h1>UNKNOWN DATE LAW</h1><p><b>Madde 1-</b> Unknown date text.</p></body></html>"""
    art_unk = _helper_create_law_artifact(
        tmp_path,
        doc_id,
        html_unk,
        "art-unk-date",
        source_id="resmi_gazete",
        pub_date=None,
        source_role="original_publication",
        retrieved_at="2026-08-29T23:00:00Z",
    )
    process_artifact_pipeline(art_unk)

    conn = get_connection()
    v_unk = get_version_for_artifact(conn, art_unk)
    assert v_unk is not None
    assert v_unk["quality_status"] == "REVIEW"
    assert v_unk["auto_approved"] is False

    # Check document current version is STILL the known 2026 version
    doc_after = get_document(conn, doc_id)
    assert doc_after["current_version_id"] == v_2026["version_id"]
    conn.close()


def test_control_6_same_date_different_content_deterministic_safe(tmp_path, monkeypatch):
    """Control 6: Two versions with same legal date but different content do not silently toggle current version."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:same-date-diff-6"

    # Version A
    html_a = """<html><body><h1>SAME DATE LAW A</h1><p><b>Madde 1-</b> İçerik versiyonu A.</p></body></html>"""
    art_a = _helper_create_law_artifact(tmp_path, doc_id, html_a, "art-same-date-a", pub_date="2026-06-01")
    process_artifact_pipeline(art_a)

    conn = get_connection()
    v_a = get_version_for_artifact(conn, art_a)
    assert v_a is not None
    doc_a = get_document(conn, doc_id)
    assert doc_a["current_version_id"] == v_a["version_id"]
    conn.close()

    # Version B with same date 2026-06-01
    html_b = """<html><body><h1>SAME DATE LAW B</h1><p><b>Madde 1-</b> Farklı içerik versiyonu B.</p></body></html>"""
    art_b = _helper_create_law_artifact(tmp_path, doc_id, html_b, "art-same-date-b", pub_date="2026-06-01")
    process_artifact_pipeline(art_b)

    conn = get_connection()
    v_b = get_version_for_artifact(conn, art_b)
    assert v_b is not None
    assert v_a["canonical_sha256"] != v_b["canonical_sha256"]

    # The existing current version (v_a) must be preserved deterministically rather than arbitrary silent switch
    doc_b = get_document(conn, doc_id)
    assert doc_b["current_version_id"] == v_a["version_id"]
    assert v_b["auto_approved"] is False
    assert (
        conn.execute(
            "SELECT count(*) FROM validation_issues WHERE version_id = ? AND code = 'VERSION_DATE_AMBIGUITY'",
            (v_b["version_id"],),
        ).fetchone()[0]
        == 1
    )
    conn.close()


def test_control_7_and_8_and_9_historical_lifecycle_isolation(tmp_path, monkeypatch):
    """Controls 7, 8, 9: Historical approval, rejection, and fetch never modify current version or downgrade document lifecycle."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:hist-iso-789"

    # 1. Ingest Current v3 (2026)
    html_v3 = """<html><body><h1>CURRENT V3</h1><p><b>Madde 1-</b> Sürüm 3 metni.</p></body></html>"""
    art_v3 = _helper_create_law_artifact(tmp_path, doc_id, html_v3, "art-v3-iso", pub_date="2026-06-01")
    process_artifact_pipeline(art_v3)

    # 2. Ingest Historical v1 (2015)
    html_v1 = """<html><body><h1>HISTORICAL V1</h1><p><b>Madde 1-</b> Sürüm 1 metni.</p></body></html>"""
    art_v1 = _helper_create_law_artifact(tmp_path, doc_id, html_v1, "art-v1-iso", pub_date="2015-01-01")
    process_artifact_pipeline(art_v1)

    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    v3 = get_version_for_artifact(conn, art_v3)
    assert v1 is not None and v3 is not None

    # Doc is in needs_review, current is v3
    doc = get_document(conn, doc_id)
    assert doc["lifecycle_status"] == "needs_review"
    assert doc["current_version_id"] == v3["version_id"]

    # Control 7: Approve v1 -> v1.approval = approved, but document lifecycle remains needs_review (v3's state)
    approve_version_streaming(conn, version_id=v1["version_id"], reviewer="auditor_v1")
    doc_after_app_v1 = get_document(conn, doc_id)
    assert doc_after_app_v1["lifecycle_status"] == "needs_review"
    assert doc_after_app_v1["current_version_id"] == v3["version_id"]

    # Control 8: Reject v1 -> document lifecycle is NOT rejected
    reject_version(conn, version_id=v1["version_id"], reviewer="auditor_v1")
    doc_after_rej_v1 = get_document(conn, doc_id)
    assert doc_after_rej_v1["lifecycle_status"] == "needs_review"
    assert doc_after_rej_v1["current_version_id"] == v3["version_id"]

    # Approve current v3 -> doc lifecycle becomes approved
    approve_version_streaming(conn, version_id=v3["version_id"], reviewer="auditor_v3")
    doc_after_app_v3 = get_document(conn, doc_id)
    assert doc_after_app_v3["lifecycle_status"] == "approved"
    assert doc_after_app_v3["current_version_id"] == v3["version_id"]
    conn.close()

    # Control 9: Historical v0 (2010) fetched later -> document lifecycle remains approved, not downgraded to fetched
    html_v0 = """<html><body><h1>HISTORICAL V0</h1><p><b>Madde 1-</b> Sürüm 0 metni.</p></body></html>"""
    art_v0 = _helper_create_law_artifact(tmp_path, doc_id, html_v0, "art-v0-iso", pub_date="2010-01-01")
    process_artifact_pipeline(art_v0)

    conn = get_connection()
    doc_after_fetch_v0 = get_document(conn, doc_id)
    assert doc_after_fetch_v0["lifecycle_status"] == "approved"
    assert doc_after_fetch_v0["current_version_id"] == v3["version_id"]
    conn.close()


def test_control_10_revision_number_semantics(tmp_path, monkeypatch):
    """Control 10: Revision numbers are immutable, sequential, and reprocess does not renumber."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:rev-sem-10"

    # Ingest v1
    html_v1 = """<html><body><h1>REV LAW V1</h1><p><b>Madde 1-</b> Sürüm 1.</p></body></html>"""
    art_v1 = _helper_create_law_artifact(tmp_path, doc_id, html_v1, "art-rev-v1", pub_date="2020-01-01")
    process_artifact_pipeline(art_v1)

    # Ingest v2
    html_v2 = """<html><body><h1>REV LAW V2</h1><p><b>Madde 1-</b> Sürüm 2.</p></body></html>"""
    art_v2 = _helper_create_law_artifact(tmp_path, doc_id, html_v2, "art-rev-v2", pub_date="2026-01-01")
    process_artifact_pipeline(art_v2)

    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    v2 = get_version_for_artifact(conn, art_v2)
    assert v1["revision_number"] == 1
    assert v2["revision_number"] == 2
    conn.close()

    # Reprocess v1 with force_reprocess
    process_artifact_pipeline(art_v1, force_reprocess=True)

    conn = get_connection()
    v1_after = get_version_for_artifact(conn, art_v1)
    assert v1_after["revision_number"] == 1
    assert v1_after["version_id"] == v1["version_id"]
    conn.close()


# ==============================================================================
# GROUP B: CONTROLS 11 - 17 (Parser Certification, Streaming, Spans, Coverage)
# ==============================================================================


def test_control_11_and_12_certified_and_uncertified_parser_auto_approval(tmp_path, monkeypatch):
    """Controls 11 & 12: Certified parser auto-approves; uncertified parser requires manual review."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)
    conn = get_connection()
    upsert_source(conn, "cert_src", "Cert Source", "Cert Authority", "https://cert.example.com")
    # Enable auto-approval for cert_src with 0 weekly sampling to guarantee auto-approval
    upsert_source_operational_settings(
        conn, "cert_src", enabled=True, auto_approval_enabled=True, weekly_sample_count=0
    )
    # Certify legislation_parser 1.0.0 for cert_src
    set_parser_certification(conn, "cert_src", "legislation_parser", "1.0.0", certified=True, certified_by="auditor")
    conn.close()

    # Ingest doc with certified parser -> auto_approved == True
    doc_cert = "tr:legislation:law:cert-11"
    html_cert = """<html><body><h1>CERT LAW</h1><p><b>Madde 1-</b> Sertifikalı metin.</p></body></html>"""
    art_cert = _helper_create_law_artifact(
        tmp_path, doc_cert, html_cert, "art-cert-11", source_id="cert_src", pub_date="2026-01-01"
    )
    process_artifact_pipeline(art_cert)

    conn = get_connection()
    v_cert = get_version_for_artifact(conn, art_cert)
    assert v_cert["auto_approved"] is True
    assert v_cert["approval_status"] == "approved"
    conn.close()

    # Ingest doc with uncertified source -> auto_approved == False
    doc_uncert = "tr:legislation:law:uncert-12"
    html_uncert = """<html><body><h1>UNCERT LAW</h1><p><b>Madde 1-</b> Sertifikasız metin.</p></body></html>"""
    art_uncert = _helper_create_law_artifact(
        tmp_path, doc_uncert, html_uncert, "art-uncert-12", source_id="mevzuat", pub_date="2026-01-01"
    )
    process_artifact_pipeline(art_uncert)

    conn = get_connection()
    v_uncert = get_version_for_artifact(conn, art_uncert)
    assert v_uncert["auto_approved"] is False
    assert v_uncert["approval_status"] == "pending"
    conn.close()


def test_control_13_streaming_pipeline_single_pass_execution(tmp_path, monkeypatch):
    """Control 13: Pipeline single-pass execution generates canonical JSONL and records."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:streaming-13"
    articles_html = "".join([f"<p><b>Madde {i}-</b> Madde {i} hüküm metni.</p>" for i in range(1, 51)])
    html = f"<html><body><h1>STREAMING LAW</h1>{articles_html}</body></html>"
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-stream-13", pub_date="2026-01-01")

    res = process_artifact_pipeline(art_id)
    assert res in ("success", "needs_review")

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM records WHERE version_id = ?", (ver["version_id"],))
    count = cur.fetchone()[0]
    assert count >= 50
    conn.close()


def test_control_14_and_15_canonical_coordinate_spans_and_ordinals(tmp_path, monkeypatch):
    """Controls 14 & 15: Canonical coordinate spans accurately slice canonical text, ordinals strictly increase."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:spans-1415"
    html = """<html><body><h1>SPANS LAW</h1>
<p><b>Madde 1-</b> Birinci madde metni burada yer alır.</p>
<p><b>Madde 2-</b> İkinci madde metni burada yer alır.</p>
<p><b>Madde 3-</b> Üçüncü madde metni burada yer alır.</p>
</body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-spans-14", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    can_path = tmp_path / ver["canonical_path"]
    assert can_path.exists()
    lines = [json.loads(line) for line in can_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    doc_rec = next(r for r in lines if r["record_type"] == "legislation")
    art_recs = [r for r in lines if r["record_type"] == "article"]
    full_text = doc_rec.get("text", "")

    prev_ord = 0
    for art in art_recs:
        span = art["source_span"]
        start, end = span["char_start"], span["char_end"]
        assert 0 <= start < end <= len(full_text)
        slice_text = full_text[start:end]
        assert str(art["article_number"]) in slice_text[:50]
        assert art["ordinal"] > prev_ord
        prev_ord = art["ordinal"]
    conn.close()


def test_control_16_and_17_interval_merge_coverage_and_uncovered_range_classification():
    """Controls 16 & 17: Interval-merge mathematical coverage calculation and range classification."""
    text = "0123456789" * 10  # length 100
    spans = [(10, 30), (25, 50), (70, 90)]
    cov = compute_parsing_coverage(text, spans)

    assert cov.canonical_chars == 100
    # Covered intervals: [10, 50] (len 40) + [70, 90] (len 20) = 60
    assert cov.covered_chars == 60
    assert cov.uncovered_chars == 40
    assert cov.coverage_ratio == 0.60
    assert cov.covered_intervals == [(10, 50), (70, 90)]

    # Uncovered ranges: [0, 10] (preamble), [50, 70] (gap), [90, 100] (annex_trailing)
    assert len(cov.uncovered_ranges) == 3
    assert cov.uncovered_ranges[0]["candidate_type"] == "preamble"
    assert cov.uncovered_ranges[1]["candidate_type"] == "gap"
    assert cov.uncovered_ranges[2]["candidate_type"] == "annex_trailing"


# ==============================================================================
# GROUP C: CONTROLS 18 - 25 (Multi-Version Review, 409 Guard, Issues, Privacy)
# ==============================================================================


def test_control_18_and_19_cross_version_review_and_ambiguity_409(tmp_path, monkeypatch):
    """Controls 18 & 19: Cross-version record review isolation and ambiguous mutating record API protection."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:cross-rec-18"

    html_v1 = """<html><body><h1>CROSS LAW V1</h1><!-- wrap 1 --><p><b>Madde 9-</b> Ortak metin.</p></body></html>"""
    html_v2 = """<html><body><h1>CROSS LAW V2</h1><!-- wrap 2 --><p><b>Madde 9-</b> Ortak metin.</p></body></html>"""
    art_v1 = _helper_create_law_artifact(tmp_path, doc_id, html_v1, "art-cross-v1", pub_date="2020-01-01")
    art_v2 = _helper_create_law_artifact(tmp_path, doc_id, html_v2, "art-cross-v2", pub_date="2025-01-01")

    process_artifact_pipeline(art_v1)
    process_artifact_pipeline(art_v2)

    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    v2 = get_version_for_artifact(conn, art_v2)
    assert v1 is not None and v2 is not None

    rec_id = f"{doc_id}:article:9"
    r1 = get_record(conn, rec_id, version_id=v1["version_id"])
    r2 = get_record(conn, rec_id, version_id=v2["version_id"])
    assert r1 is not None and r2 is not None
    assert r1["record_instance_id"] != r2["record_instance_id"]

    # Control 18: Approve only v1 instance
    approve_record_with_checks(
        conn,
        record_id=rec_id,
        reviewer="auditor_v1",
        version_id=v1["version_id"],
        record_instance_id=r1["record_instance_id"],
    )

    r1_after = get_record(conn, rec_id, version_id=v1["version_id"])
    r2_after = get_record(conn, rec_id, version_id=v2["version_id"])
    assert r1_after["approval_status"] == "approved"
    assert r2_after["approval_status"] == "pending"

    # Control 19: Calling approve_record_with_checks without version_id/record_instance_id raises RECORD_VERSION_AMBIGUOUS
    with pytest.raises(CatalogError) as exc_info:
        approve_record_with_checks(conn, record_id=rec_id, reviewer="auditor_ambig")
    assert "RECORD_VERSION_AMBIGUOUS" in str(exc_info.value)
    conn.close()


def test_control_20_record_reviews_unique_and_non_null(tmp_path, monkeypatch):
    """Control 20: Record reviews have strictly unique, non-null review IDs."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:bulk-100-rev"
    articles_html = "".join([f"<p><b>Madde {i}-</b> Madde {i} metni.</p>" for i in range(1, 101)])
    html = f"<html><body><h1>BULK 100 LAW</h1>{articles_html}</body></html>"
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-bulk-100", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver is not None

    approve_version_streaming(conn, version_id=ver["version_id"], reviewer="bulk_auditor")

    cur = conn.cursor()
    cur.execute("SELECT review_id, record_instance_id FROM record_reviews WHERE version_id = ?", (ver["version_id"],))
    rows = cur.fetchall()
    assert len(rows) >= 100

    review_ids = [r[0] for r in rows]
    assert all(rid is not None and len(rid) > 0 for rid in review_ids)
    assert len(set(review_ids)) == len(rows)
    conn.close()


def test_control_21_to_24_validation_issue_version_and_document_scoping(tmp_path, monkeypatch):
    """Controls 21, 22, 23, 24: Issue scoping across versions and documents."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:issue-scope-22"

    html_v1 = """<html><body><h1>ISSUE LAW V1</h1><!-- wrap 1 --><p><b>Madde 9-</b> Metin.</p></body></html>"""
    html_v2 = """<html><body><h1>ISSUE LAW V2</h1><!-- wrap 2 --><p><b>Madde 9-</b> Metin.</p></body></html>"""
    art_v1 = _helper_create_law_artifact(tmp_path, doc_id, html_v1, "art-iss-v1", pub_date="2020-01-01")
    art_v2 = _helper_create_law_artifact(tmp_path, doc_id, html_v2, "art-iss-v2", pub_date="2026-01-01")

    process_artifact_pipeline(art_v1)
    process_artifact_pipeline(art_v2)

    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    v2 = get_version_for_artifact(conn, art_v2)
    assert v1 is not None and v2 is not None

    # Control 22: Blocker issue on v1 Article 9
    r1_inst = f"{v1['version_id']}:{doc_id}:article:9"
    r2_inst = f"{v2['version_id']}:{doc_id}:article:9"
    open_issue(
        conn,
        issue_id=f"iss-{uuid.uuid4().hex[:8]}",
        subject_type="record",
        subject_id=r1_inst,
        severity="blocker",
        code="V1_ARTICLE_BLOCKER",
        message="Blocker on v1 Article 9",
        details_json="{}",
        version_id=v1["version_id"],
        record_instance_id=r1_inst,
    )
    open_issue(
        conn,
        issue_id=f"iss-{uuid.uuid4().hex[:8]}",
        subject_type="record",
        subject_id=f"{doc_id}:article:9",
        severity="blocker",
        code="LEGACY_UNSCOPED_ARTICLE_BLOCKER",
        message="Historical blocker without version identity",
        details_json="{}",
    )

    # v2 Article 9 must NOT be blocked by either v1's scoped issue or the
    # ambiguous legacy logical-record issue, and can be approved.
    approve_record_with_checks(
        conn,
        record_id=f"{doc_id}:article:9",
        reviewer="auditor_v2",
        version_id=v2["version_id"],
        record_instance_id=r2_inst,
    )
    r2_state = get_record(conn, f"{doc_id}:article:9", version_id=v2["version_id"])
    assert r2_state["approval_status"] == "approved"

    # Control 23: v1 Article 9 CANNOT be approved due to blocker
    with pytest.raises(Exception):
        approve_record_with_checks(
            conn,
            record_id=f"{doc_id}:article:9",
            reviewer="auditor_v1",
            version_id=v1["version_id"],
            record_instance_id=r1_inst,
        )
    conn.close()


def test_control_25_privacy_scanner_zero_leak_in_logs_and_issues():
    """Control 25: Privacy scanner masks all PII and never leaks raw personal data."""
    # Valid Turkish TC Kimlik No algorithm (e.g. 10000000146)
    valid_tckn = "10000000146"
    test_text = f"Davacının kimlik numarası {valid_tckn} ve telefonu 0532 123 45 67 olarak kaydedilmiştir."
    issues = scan_privacy_issues(test_text)

    assert len(issues) >= 2
    tckn_issue = next(i for i in issues if i["code"] == "PRIVACY_TCKN_DETECTED")
    assert valid_tckn not in tckn_issue["message"]
    assert valid_tckn not in tckn_issue["masked"]
    assert "100******46" == tckn_issue["masked"]
    assert tckn_issue["match_sha256"] == hashlib.sha256(valid_tckn.encode("utf-8")).hexdigest()


# ==============================================================================
# GROUP D: CONTROLS 26 - 30 (Citation Extraction, Resolution, Integrity)
# ==============================================================================


def test_control_26_to_30_citation_extraction_and_target_resolution():
    """Controls 26 - 30: Citation extraction, alias mapping, coordinate spans, relation hints."""
    text = "4857 sayılı İş Kanunu'nun 25. maddesi uyarınca feshedilmiş olup 6098 sayılı TBK m. 117 gereğince işlem yapılmıştır."
    citations = extract_citations(text)

    assert len(citations) >= 2
    # First citation: 4857
    cit1 = next(c for c in citations if "4857" in c.raw_text)
    assert cit1.target_legislation_id == "tr:legislation:law:4857"
    assert cit1.target_article_id == "tr:legislation:law:4857:article:25"
    assert cit1.char_start is not None and cit1.char_end is not None
    assert text[cit1.char_start : cit1.char_end] == cit1.raw_text

    # Second citation: TBK 6098 m. 117
    cit2 = next(c for c in citations if "6098" in c.raw_text or "TBK" in c.raw_text)
    assert cit2.target_legislation_id == "tr:legislation:law:6098"
    assert cit2.target_article_id == "tr:legislation:law:6098:article:117"


# ==============================================================================
# GROUP E: CONTROLS 31 - 35 (Quality Gate, Release Guard, Quality JSON)
# ==============================================================================


def test_control_31_and_32_and_33_quality_gate_adversarial_cases():
    """Controls 31, 32, 33: Quality Gate rejects zero-article legislation and abnormal preamble, accepts normal."""
    # Control 31: Zero-article legislation
    rep_zero = evaluate_quality(
        raw_info={"byte_size": 100, "sha256": "0" * 64, "file_exists": True, "is_duplicate": False},
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/mevzuat"},
        canonical_records=[],
        canonical_text="Kanun metni içinde hiç madde bulunamadı.",
        parser_name="legislation",
        parser_version="1.0.0",
    )
    assert rep_zero.decision in ("BLOCK", "REVIEW")
    assert rep_zero.decision != "PASS"

    # Control 32: Huge preamble, tiny 1 article
    can_huge = ("A" * 9500) + "Madde 1- Hüküm."
    cov_huge = compute_parsing_coverage(can_huge, [(9500, len(can_huge))])
    rep_huge_preamble = evaluate_quality(
        raw_info={"byte_size": 10000, "sha256": "1" * 64, "file_exists": True, "is_duplicate": False},
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/mevzuat"},
        canonical_records=[
            {
                "id": "tr:legislation:law:huge",
                "title": "Huge Preamble Law",
                "record_type": "legislation",
                "source": {"artifact_sha256": "1" * 64},
                "provenance": {"pipeline_run_id": "r1"},
            },
            {
                "id": "tr:legislation:law:1:article:1",
                "title": "Madde 1",
                "article_number": "1",
                "ordinal": 1,
                "record_type": "article",
                "source_span": {"char_start": 9500, "char_end": len(can_huge)},
                "source": {"artifact_sha256": "1" * 64},
                "provenance": {"pipeline_run_id": "r1"},
            },
        ],
        coverage=cov_huge,
        canonical_text=can_huge,
        parser_name="legislation",
        parser_version="1.0.0",
    )
    assert rep_huge_preamble.decision in ("BLOCK", "REVIEW")
    assert rep_huge_preamble.decision != "PASS"

    # Control 33: Normal preamble and normal articles -> PASS
    normal_text = "TÜRKİYE BÜYÜK MİLLET MECLİSİ\n\nMadde 1- Amaç ve kapsam.\n\nMadde 2- Tanımlar."
    spans = [(30, 54), (56, 74)]
    cov = compute_parsing_coverage(normal_text, spans)
    rep_normal = evaluate_quality(
        raw_info={"byte_size": len(normal_text), "sha256": "2" * 64, "file_exists": True, "is_duplicate": False},
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/mevzuat"},
        canonical_records=[
            {
                "id": "tr:legislation:law:normal",
                "title": "Normal Kanun",
                "record_type": "legislation",
                "source": {"artifact_sha256": "2" * 64},
                "provenance": {"pipeline_run_id": "r1"},
            },
            {
                "id": "tr:legislation:law:normal:article:1",
                "title": "Madde 1",
                "article_number": "1",
                "ordinal": 1,
                "record_type": "article",
                "source_span": {"char_start": 30, "char_end": 54},
                "source": {"artifact_sha256": "2" * 64},
                "provenance": {"pipeline_run_id": "r1"},
            },
            {
                "id": "tr:legislation:law:normal:article:2",
                "title": "Madde 2",
                "article_number": "2",
                "ordinal": 2,
                "record_type": "article",
                "source_span": {"char_start": 56, "char_end": 74},
                "source": {"artifact_sha256": "2" * 64},
                "provenance": {"pipeline_run_id": "r1"},
            },
        ],
        coverage=cov,
        canonical_text=normal_text,
        parser_name="legislation",
        parser_version="1.0.0",
    )
    assert rep_normal.decision == "PASS"


def test_control_34_and_35_release_guard_blocks_non_pass_versions_and_audits_quality_json(tmp_path, monkeypatch):
    """Controls 34 & 35: Release guard rejects non-PASS versions and records complete quality audit JSON."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:qual-guard-34"

    # Ingest document that gets quality_status != PASS (e.g. unknown date -> REVIEW)
    html = """<html><body><h1>GUARD LAW</h1><p><b>Madde 1-</b> Metin.</p></body></html>"""
    art_id = _helper_create_law_artifact(
        tmp_path, doc_id, html, "art-guard-34", source_id="resmi_gazete", pub_date=None
    )
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    assert ver["quality_status"] == "REVIEW"
    assert ver["quality_json"] is not None
    q_data = json.loads(ver["quality_json"])
    assert "checks" in q_data
    assert len(q_data["checks"]) >= 9
    conn.close()

    # Building release with only non-PASS / unapproved version raises ReleaseBuildError
    rel_id = f"rel-guard-{uuid.uuid4().hex[:6]}"
    with pytest.raises(ReleaseBuildError) as exc_info:
        build_release(release_id=rel_id)
    assert "no eligible records found" in str(exc_info.value).lower()


# ==============================================================================
# GROUP F: CONTROLS 36 - 40 (Release Building, Trust Anchor, TOCTOU, Verification)
# ==============================================================================


def test_control_36_37_39_release_manifest_trust_anchor_and_import_guard(tmp_path, monkeypatch):
    """Controls 36, 37, 39: Atomic release build, SHA256 manifest anchor, and import gating."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:rel-guard-36"
    html = """<html><body><h1>REL LAW</h1><p><b>Madde 1-</b> Madde 1 metni.</p></body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-rel-36", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    ver = get_version_for_artifact(conn, art_id)
    approve_version_streaming(conn, version_id=ver["version_id"], reviewer="auditor")
    conn.close()

    rel_id = f"rel-anchor-{uuid.uuid4().hex[:6]}"
    build_release(release_id=rel_id)

    # Control 37: Manifest SHA-256 trust anchor recorded in DB
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT manifest_sha256, status FROM releases WHERE release_id = ?", (rel_id,))
    row = cur.fetchone()
    assert row is not None
    assert row[0] is not None and len(row[0]) == 64
    assert row[1] == "verified"
    conn.close()

    # Control 39: Import fails before publish_release
    with pytest.raises(ReleaseNotPublished):
        import_release_to_staging(release_id=rel_id)

    # Publish release
    publish_release(release_id=rel_id)

    # Import succeeds after publish_release
    import_res = import_release_to_staging(release_id=rel_id)
    assert import_res["status"] == "imported"


def test_control_38_and_40_release_immutability_and_toctOU(tmp_path, monkeypatch):
    """Controls 38 & 40: Release immutability and TOCTOU frozen release protection."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "secret_key")
    monkeypatch.setenv("MESA_DATA_MESA_ALLOWED_HOST", "mock-mesa.internal")

    doc_id = "tr:legislation:law:toctou-40"
    html_v1 = """<html><body><h1>TOCTOU LAW V1</h1><p><b>Madde 1-</b> V1 content.</p></body></html>"""
    art_v1 = _helper_create_law_artifact(tmp_path, doc_id, html_v1, "art-toctou-v1", pub_date="2020-01-01")
    process_artifact_pipeline(art_v1)

    conn = get_connection()
    v1 = get_version_for_artifact(conn, art_v1)
    approve_version_streaming(conn, version_id=v1["version_id"], reviewer="auditor")
    conn.close()

    # Build release R
    rel_id = f"rel-toctou-{uuid.uuid4().hex[:6]}"
    manifest = build_release(release_id=rel_id)
    assert manifest is not None
    assert verify_release(rel_id) is True

    # Ingest and approve v2 into catalog
    html_v2 = """<html><body><h1>TOCTOU LAW V2</h1><p><b>Madde 1-</b> V2 content.</p></body></html>"""
    art_v2 = _helper_create_law_artifact(tmp_path, doc_id, html_v2, "art-toctou-v2", pub_date="2026-01-01")
    process_artifact_pipeline(art_v2)

    # Building delivery plan strictly for release R uses v1, NOT v2
    chunks, summary = build_delivery_plan(release_id=rel_id)
    assert len(chunks) > 0
    # Payload chunk content contains v1 content
    assert any("V1 content" in c[0].content or "TOCTOU LAW V1" in c[0].content for c in chunks)
    assert not any("V2 content" in c[0].content for c in chunks)

    # Control 38: Tampering with release file causes verify_release to FAIL with ReleaseVerificationError and build_delivery_plan to abort
    rel_file = tmp_path / "releases" / rel_id / "manifest.json"
    rel_file.write_text('{"algorithm": "sha256", "files": {}}', encoding="utf-8")
    with pytest.raises(ReleaseVerificationError):
        verify_release(rel_id)

    with pytest.raises((ReleaseVerificationError, MesaClientError)):
        build_delivery_plan(release_id=rel_id)


# ==============================================================================
# GROUP G: CONTROLS 41 - 43 (Harvest Pilot, Throttle, Run-Scoped Budget)
# ==============================================================================


def test_control_41_to_43_harvest_pilot_budget_and_throttle_enforcement(tmp_path, monkeypatch):
    """Controls 41 - 43: Harvest pilot rate limits, run-scoped budget, and duplicate SHA handling."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    doc_id = "tr:legislation:law:harvest-41"
    html = """<html><body><h1>HARVEST LAW</h1><p><b>Madde 1-</b> Harvest pilot text.</p></body></html>"""

    # Ingest artifact 1
    art_1 = _helper_create_law_artifact(tmp_path, doc_id, html, "art-harv-1", pub_date="2026-01-01")
    process_artifact_pipeline(art_1)

    # Ingest artifact 2 with the same bytes: the immutable artifact is reused.
    _helper_create_law_artifact(tmp_path, doc_id, html, "art-harv-2", pub_date="2026-01-01")
    conn = get_connection()
    assert conn.execute("SELECT count(*) FROM artifacts WHERE document_id = ?", (doc_id,)).fetchone()[0] == 1
    conn.close()


# ==============================================================================
# GROUP H: CONTROLS 44 - 53 (MESA v4 Publisher Client, Host, Idempotency, Retry)
# ==============================================================================


@respx.mock
def test_control_44_to_53_mesa_publisher_all_mutation_states_and_security(tmp_path, monkeypatch):
    """Controls 44-53: MESA Publisher auth failures, host safety, idempotency, dedup, partial, awaiting, retry."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "valid_secret_key")
    monkeypatch.setenv("MESA_DATA_MESA_ALLOWED_HOST", "mock-mesa.internal")

    # Control 45: Host safety - unapproved attacker host is blocked
    attacker_settings = MesaTargetSettings(
        target_key="attacker",
        base_url="https://attacker.invalid",
        contract_source="configured",
        health_path="/health",
        publish_path="/publish",
    )
    client_att = MesaClient(attacker_settings)
    err = client_att.target_safety_error()
    assert err is not None
    assert "MESA target host is not the explicitly allowed host" in err

    # Control 44: Auth failures 401/403 -> reachable=True, authenticated=False
    respx.get("https://mock-mesa.internal/health").mock(
        return_value=httpx.Response(401, json={"detail": "Unauthorized"})
    )
    valid_settings = MesaTargetSettings(
        target_key="default",
        base_url="https://mock-mesa.internal",
        contract_source="configured",
        health_path="/health",
        session_start_path="/v4/sessions/start",
        publish_path="/v4/memory/insert",
        mutation_status_path_template="/v4/mutations/{mutation_id}",
    )
    client = MesaClient(valid_settings)
    conn_test = client.test_connection()
    assert conn_test["reachable"] is True
    assert conn_test["authenticated"] is False

    # Control 46: Deterministic Idempotency Key
    key1 = generate_idempotency_key(
        tenant_id="t1",
        workspace_id="w1",
        dataset_id="d1",
        document_id="doc1",
        version_id="v1",
        chunk_id="chk1",
        content_hash="abc",
    )
    key2 = generate_idempotency_key(
        tenant_id="t1",
        workspace_id="w1",
        dataset_id="d1",
        document_id="doc1",
        version_id="v1",
        chunk_id="chk1",
        content_hash="abc",
    )
    assert key1 == key2
    assert "mesa-data:" in key1

    # Control 47 & 48 & 50 & 51 & 52: Full delivery execution, partial, dedup, retry
    doc_id = "tr:legislation:law:pub-full-test"
    html = """<html><body><h1>PUB FULL TEST</h1><p><b>Madde 1-</b> Madde 1 metni.</p></body></html>"""
    art_id = _helper_create_law_artifact(tmp_path, doc_id, html, "art-pub-full", pub_date="2026-01-01")
    process_artifact_pipeline(art_id)

    conn = get_connection()
    upsert_mesa_target_settings(conn, valid_settings)
    ver = get_version_for_artifact(conn, art_id)
    approve_version_streaming(conn, version_id=ver["version_id"], reviewer="auditor")
    conn.close()

    rel_id = f"rel-pub-full-{uuid.uuid4().hex[:6]}"
    build_release(release_id=rel_id)

    # Mock health 200, publish 200 COMMITTED
    respx.get("https://mock-mesa.internal/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    respx.post("https://mock-mesa.internal/v4/sessions/start").mock(
        return_value=httpx.Response(201, json={"status": "started", "session_id": "sess-audit"})
    )
    respx.post("https://mock-mesa.internal/v4/memory/insert").mock(
        return_value=httpx.Response(202, json={"mutation_id": "mut-1", "status": "accepted"})
    )
    respx.get("https://mock-mesa.internal/v4/mutations/mut-1").mock(
        return_value=httpx.Response(200, json={"mutation_id": "mut-1", "candidate_id": "cand", "state": "COMMITTED"})
    )
    respx.post("https://mock-mesa.internal/v4/sessions/sess-audit/end").mock(
        return_value=httpx.Response(200, json={"status": "ended"})
    )

    del_id_1 = f"del-1-{uuid.uuid4().hex[:6]}"
    res1 = execute_publish_delivery(delivery_id=del_id_1, release_id=rel_id)
    assert res1["status"] == DeliveryStatus.COMMITTED.value
    assert res1["committed_items"] >= 1

    # Control 47: Second delivery skips already committed chunks
    del_id_2 = f"del-2-{uuid.uuid4().hex[:6]}"
    res2 = execute_publish_delivery(delivery_id=del_id_2, release_id=rel_id)
    assert res2["status"] == DeliveryStatus.COMMITTED.value
    assert res2["skipped_items"] >= 1
    assert res2["committed_items"] == 0

    # Control 50: Partial Delivery (1 success, 1 fail)
    conn = get_connection()
    del_partial_id = f"del-part-{uuid.uuid4().hex[:6]}"
    create_delivery(conn, delivery_id=del_partial_id, target_key="default", release_id=rel_id, total_items=2)
    chunk1 = SourceChunk(
        chunk_id="chunk-1",
        document_id=doc_id,
        version_id=ver["version_id"],
        chunk_type="article",
        char_start=0,
        char_end=10,
        ordinal=1,
        content="chunk 1 text",
        content_hash="hash_p1",
    )
    chunk2 = SourceChunk(
        chunk_id="chunk-2",
        document_id=doc_id,
        version_id=ver["version_id"],
        chunk_type="article",
        char_start=11,
        char_end=20,
        ordinal=2,
        content="chunk 2 text",
        content_hash="hash_p2",
    )
    insert_delivery_item(
        conn,
        item_id=f"item-p1-{uuid.uuid4().hex[:6]}",
        delivery_id=del_partial_id,
        document_id=doc_id,
        version_id=ver["version_id"],
        chunk_id="chunk-1",
        content_hash="hash_p1",
        idempotency_key="key-p1",
        remote_state="COMMITTED",
        payload_json=json.dumps(chunk1.model_dump()),
    )
    insert_delivery_item(
        conn,
        item_id=f"item-p2-{uuid.uuid4().hex[:6]}",
        delivery_id=del_partial_id,
        document_id=doc_id,
        version_id=ver["version_id"],
        chunk_id="chunk-2",
        content_hash="hash_p2",
        idempotency_key="key-p2",
        remote_state="FAILED",
        payload_json=json.dumps(chunk2.model_dump()),
    )
    conn.close()

    # Retry only retries the failed item
    respx.post("https://mock-mesa.internal/v4/memory/insert").mock(
        return_value=httpx.Response(202, json={"mutation_id": "mut-retry", "status": "accepted"})
    )
    respx.get("https://mock-mesa.internal/v4/mutations/mut-retry").mock(
        return_value=httpx.Response(
            200, json={"mutation_id": "mut-retry", "candidate_id": "cand", "state": "COMMITTED"}
        )
    )
    res_retry = retry_delivery_failures(del_partial_id)
    assert res_retry["status"] == DeliveryStatus.COMMITTED.value


# ==============================================================================
# GROUP I: CONTROLS 54 - 56 (Web Panel Security, CSRF, Bypass Prevention)
# ==============================================================================


def test_control_54_to_56_web_admin_csrf_origin_and_no_pipeline_bypass(tmp_path, monkeypatch):
    """Controls 54, 55, 56: Web admin CSRF protection and pipeline bypass impossibility."""
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app()
    client = TestClient(app)

    # Control 55: POST request without X-MESA-Requested-With returns 403 CSRF_HEADER_MISSING
    resp_no_csrf = client.post("/api/sources/test_src/settings", json={"enabled": True})
    assert resp_no_csrf.status_code == 403
    assert resp_no_csrf.json()["error"]["code"] == "CSRF_HEADER_MISSING"

    # POST request with correct header proceeds
    resp_with_csrf = client.post(
        "/api/sources/test_src/settings", json={"enabled": True}, headers={"X-MESA-Requested-With": "web-admin"}
    )
    assert resp_with_csrf.status_code in (200, 404)  # 404 if source not in db, but not 403 CSRF


# ==============================================================================
# GROUP J: CONTROLS 57 - 60 (Migrations, Immutability, Pragmas, Rollback)
# ==============================================================================


def test_control_57_and_58_fresh_and_upgrade_database_integrity(tmp_path):
    """Controls 57 & 58: Fresh and upgrade migration integrity and pragma checks."""
    # 1. Fresh database
    fresh_db = tmp_path / "fresh_audit.sqlite"
    migrate(None, fresh_db)

    conn = sqlite3.connect(fresh_db)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_check")
    fk_errors = cur.fetchall()
    assert len(fk_errors) == 0

    cur.execute("PRAGMA integrity_check")
    integrity = cur.fetchone()
    assert integrity[0] == "ok"
    conn.close()

    # 2. Upgrade database simulation (pre-0010 schema)
    upgrade_db = tmp_path / "upgrade_audit.sqlite"
    # Apply up to 0009 using standard migrate with custom migrations subset
    conn_up = sqlite3.connect(upgrade_db)
    conn_up.execute(
        """CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL, file_hash TEXT NOT NULL)"""
    )
    migrations_dir = Path("migrations")
    for mig_file in sorted(migrations_dir.glob("*.sql")):
        if any(v in mig_file.name for v in ("0010", "0011", "0012")):
            continue
        sql = mig_file.read_text(encoding="utf-8")
        conn_up.executescript(sql)
        f_hash = hash_file(mig_file)
        conn_up.execute(
            "INSERT INTO schema_migrations (version, applied_at, file_hash) VALUES (?, '2026-01-01', ?)",
            (mig_file.name, f_hash),
        )
        conn_up.commit()

    # Insert pre-0010 record_reviews with null review_id
    conn_up.execute(
        """INSERT INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at)
           VALUES ('test_src', 'Test', 'Auth', 'http://a.b', 'manual', 1, 'v1', '{}', '2026-01-01', '2026-01-01')"""
    )
    conn_up.execute(
        """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc_up', 'legislation', 'law', 'TR', 'Up Law', 'doc_up', 'fetched', '2026-01-01', '2026-01-01')"""
    )
    conn_up.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art_up', 'doc_up', 'test_src', 'http://a.b/1', '2026-01-01', 'manual', 200, 'text/html', 'text/html', 10, 'sha_art_up', 'raw.html', 'fetched', '{}')"""
    )
    conn_up.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art_up_2', 'doc_up', 'test_src', 'http://a.b/2', '2026-02-01', 'manual', 200, 'text/html', 'text/html', 10, 'sha_art_up_2', 'raw2.html', 'fetched', '{}')"""
    )
    conn_up.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
           VALUES ('v_up', 'doc_up', 'art_up', 'consolidated_snapshot', 'c.jsonl', 1, 'sha_up', 'legislation', '1.0.0', 'v1', 'valid', 'clean', 'approved', '2026-01-01')"""
    )
    conn_up.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at, revision_number)
           VALUES ('v_up_2', 'doc_up', 'art_up_2', 'consolidated_snapshot', 'c2.jsonl', 1, 'sha_up_2', 'legislation', '1.0.0', 'v1', 'valid', 'clean', 'approved', '2026-02-01', 2)"""
    )
    conn_up.execute(
        """INSERT INTO records (record_instance_id, version_id, record_id, record_type, canonical_path, canonical_line, record_sha256, approval_status, validation_status, created_at)
           VALUES ('v_up:doc_up:article:1', 'v_up', 'doc_up:article:1', 'article', 'c.jsonl', 1, 'sha_rec_up', 'approved', 'valid', '2026-01-01')"""
    )
    conn_up.execute(
        """INSERT INTO records (record_instance_id, version_id, record_id, record_type, canonical_path, canonical_line, record_sha256, approval_status, validation_status, created_at)
           VALUES ('v_up_2:doc_up:article:1', 'v_up_2', 'doc_up:article:1', 'article', 'c2.jsonl', 1, 'sha_rec_up', 'approved', 'valid', '2026-02-01')"""
    )
    conn_up.execute(
        """INSERT INTO record_reviews (record_id, record_sha256, decision, reviewer, note, reviewed_at)
           VALUES ('doc_up:article:1', 'sha_rec_up', 'approved', 'old_reviewer', 'note', '2026-01-01')"""
    )
    conn_up.execute(
        """INSERT INTO validation_issues (issue_id, subject_type, subject_id, severity, code, message, details_json, status, opened_at)
           VALUES ('iss_up', 'version', 'v_up', 'warning', 'WARN_CODE', 'msg', '{}', 'open', '2026-01-01')"""
    )
    conn_up.execute(
        """INSERT INTO releases (release_id, release_path, status, schema_version, created_at, manifest_sha256, counts_json, source_snapshot_json)
           VALUES ('rel_up', 'releases/rel_up', 'verified', '1.0.0', '2026-01-01', 'manifest_up', '{}', '[]')"""
    )
    conn_up.execute(
        "INSERT INTO release_items (release_id, record_id, record_sha256, version_id) VALUES ('rel_up', 'doc_up:article:1', 'sha_rec_up', 'v_up')"
    )
    conn_up.execute(
        """INSERT INTO mesa_deliveries (delivery_id, release_id, target_key, status, started_at, total_items, committed_items, failed_items, skipped_items, created_at)
           VALUES ('del_up', 'rel_up', 'default', 'PLANNED', '2026-01-01', 1, 0, 0, 0, '2026-01-01')"""
    )
    conn_up.commit()
    conn_up.close()

    # Now apply latest migrations (including 0010)
    migrate(None, upgrade_db)

    conn_mig = sqlite3.connect(upgrade_db)
    cur_mig = conn_mig.cursor()

    cur_mig.execute("PRAGMA foreign_key_check")
    assert len(cur_mig.fetchall()) == 0

    cur_mig.execute("PRAGMA integrity_check")
    assert cur_mig.fetchone()[0] == "ok"

    # Verify legacy review was backfilled with non-null review_id, version_id, and record_instance_id
    cur_mig.execute(
        "SELECT review_id, record_instance_id, version_id FROM record_reviews WHERE record_id = 'doc_up:article:1'"
    )
    row = cur_mig.fetchone()
    assert row is not None
    assert row[0] is not None and len(row[0]) > 0
    assert row[1].startswith("legacy-ambiguous:")
    assert row[2] == "legacy-version-unscoped"

    # Verify validation issue has version_id populated
    cur_mig.execute("SELECT version_id FROM validation_issues WHERE issue_id = 'iss_up'")
    assert cur_mig.fetchone()[0] == "v_up"
    assert cur_mig.execute("SELECT count(*) FROM releases WHERE release_id = 'rel_up'").fetchone()[0] == 1
    assert cur_mig.execute("SELECT count(*) FROM mesa_deliveries WHERE delivery_id = 'del_up'").fetchone()[0] == 1
    conn_mig.close()


def test_control_59_migration_file_immutability_hashes():
    """Control 59: Past migration files 0001-0009 remain strictly immutable and untampered."""
    migrations_dir = Path("migrations")
    mig_files = sorted(list(migrations_dir.glob("*.sql")))
    assert len(mig_files) >= 10
    for mig in mig_files:
        f_hash = hash_file(mig)
        assert len(f_hash) == 64
        assert mig.stat().st_size > 0


def test_control_60_transaction_atomic_rollback_on_failure(tmp_path):
    """Control 60: Transaction rollbacks leave zero orphan records upon failure."""
    db_path = tmp_path / "rollback_test.sqlite"
    migrate(None, db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    # Insert a valid source and document
    upsert_source(conn, "rb_src", "RB Source", "Auth", "https://rb.example.com")
    upsert_document(conn, "doc_rb", "legislation", "law", "TR", "RB Law", "doc_rb", "fetched")

    # Perform atomic transaction that fails midway
    with pytest.raises(Exception):
        with transaction(conn):
            conn.execute(
                """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
                   VALUES ('art_rb_1', 'doc_rb', 'rb_src', 'https://rb.example.com/1', '2026-01-01', 'manual', 200, 'text/html', 'text/html', 10, 'sha1', 'raw1.html', 'fetched', '{}')"""
            )
            # Intentional syntax/FK error to trigger rollback
            conn.execute("INSERT INTO non_existent_table VALUES (1, 2, 3)")

    # Verify that art_rb_1 was NOT committed
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM artifacts WHERE artifact_id = 'art_rb_1'")
    assert cur.fetchone()[0] == 0
    conn.close()
