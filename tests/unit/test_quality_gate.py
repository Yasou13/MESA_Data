import hashlib
import json

import pytest

from mesa_legal_data.catalog import (
    BlockingValidationIssueExists,
    approve_version_streaming,
    get_connection,
    get_db_path,
    insert_artifact,
    iter_records_for_release,
    migrate,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.parsers.coverage import compute_parsing_coverage
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.quality import evaluate_quality


@pytest.fixture
def quality_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)
    return tmp_path


def test_evaluate_quality_healthy_pass():
    canonical_text = "MADDE 1 - Kanun amacı.\nBu kanunun amacı düzeni sağlamaktır."
    records = [
        {
            "id": "tr:legislation:law:100",
            "record_type": "legislation",
            "title": "100 Sayılı Kanun",
            "source": {"artifact_sha256": "a" * 64},
            "provenance": {"pipeline_run_id": "run-1"},
        },
        {
            "id": "tr:legislation:law:100:article:1",
            "record_type": "article",
            "source_span": {"char_start": 0, "char_end": 22, "ordinal": 1},
            "source": {"artifact_sha256": "a" * 64},
            "provenance": {"pipeline_run_id": "run-1"},
        },
    ]
    cov = compute_parsing_coverage(canonical_text, [(0, 22)])
    report = evaluate_quality(
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/law.html"},
        raw_info={"byte_size": 1024, "sha256": "a" * 64, "file_exists": True},
        canonical_records=records,
        canonical_text=canonical_text,
        coverage=cov,
        privacy_issues=[],
    )

    assert report.decision == "PASS"
    assert "PASS" in report.summary


def test_evaluate_quality_suspicious_review():
    canonical_text = "MADDE 1 - Kanun metni.\nEksik karakter \ufffd içeriyor."
    records = [
        {
            "id": "tr:legislation:law:101",
            "record_type": "legislation",
            "title": "101 Sayılı Kanun",
            "source": {"artifact_sha256": "b" * 64},
            "provenance": {"pipeline_run_id": "run-2"},
        },
        {
            "id": "tr:legislation:law:101:article:1",
            "record_type": "article",
            "source_span": {"char_start": 0, "char_end": 20, "ordinal": 1},
            "source": {"artifact_sha256": "b" * 64},
            "provenance": {"pipeline_run_id": "run-2"},
        },
    ]
    report = evaluate_quality(
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/law.html"},
        raw_info={"byte_size": 1024, "sha256": "b" * 64, "file_exists": True},
        canonical_records=records,
        canonical_text=canonical_text,
        coverage=None,
        privacy_issues=[],
    )

    assert report.decision == "REVIEW"


def test_evaluate_quality_corrupt_block():
    canonical_text = "MADDE 1 - Kanun metni."
    records = [
        {
            "id": "tr:legislation:law:102",
            "record_type": "legislation",
            "title": "102 Sayılı Kanun",
            "source": {"artifact_sha256": "c" * 64},
            "provenance": {"pipeline_run_id": "run-3"},
        },
        {
            "id": "tr:legislation:law:102:article:1",
            "record_type": "article",
            "source_span": {"char_start": 50, "char_end": 10, "ordinal": 1},  # Invalid inverted span
            "source": {"artifact_sha256": "c" * 64},
            "provenance": {"pipeline_run_id": "run-3"},
        },
    ]
    report = evaluate_quality(
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/law.html"},
        raw_info={"byte_size": 1024, "sha256": "c" * 64, "file_exists": True},
        canonical_records=records,
        canonical_text=canonical_text,
        coverage=None,
        privacy_issues=[],
    )

    assert report.decision == "BLOCK"


def _quality_report_for_text(canonical_text, records, coverage=None):
    return evaluate_quality(
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/law.html"},
        raw_info={"byte_size": max(1, len(canonical_text.encode())), "sha256": "d" * 64, "file_exists": True},
        canonical_records=records,
        canonical_text=canonical_text,
        coverage=coverage,
        privacy_issues=[],
    )


def test_quality_adversarial_inputs_never_pass():
    provenance = {"source": {"artifact_sha256": "d" * 64}, "provenance": {"pipeline_run_id": "run-audit"}}

    assert _quality_report_for_text("", []).decision == "BLOCK"

    canonical = "MADDE 1 - Birinci metin.\n\nMADDE 2 - İkinci metin."
    shifted_article = {
        "id": "law:article:1",
        "record_type": "article",
        "article_number": "1",
        "text": "Birinci metin.",
        "source_span": {"char_start": canonical.index("MADDE 2"), "char_end": len(canonical)},
        **provenance,
    }
    legislation = {"id": "law", "record_type": "legislation", "title": "Audit Law", **provenance}
    assert _quality_report_for_text(canonical, [legislation, shifted_article]).decision == "BLOCK"

    severe_mojibake = "MADDE 1 - " + ("\ufffd" * 20)
    valid_span_article = {
        "id": "law:article:1",
        "record_type": "article",
        "article_number": "1",
        "text": "\ufffd" * 20,
        "source_span": {"char_start": 0, "char_end": len(severe_mojibake)},
        **provenance,
    }
    severe_report = _quality_report_for_text(severe_mojibake, [legislation, valid_span_article])
    assert severe_report.decision == "BLOCK"

    first = "MADDE 1 - Başlangıç."
    second = "MADDE 2 - Bitiş."
    missing_middle = first + ("\nKAYIP BÖLÜM" * 600) + "\n" + second
    second_start = missing_middle.rindex("MADDE 2")
    articles = [
        {
            "id": "law:article:1",
            "record_type": "article",
            "article_number": "1",
            "text": "Başlangıç.",
            "source_span": {"char_start": 0, "char_end": len(first)},
            **provenance,
        },
        {
            "id": "law:article:2",
            "record_type": "article",
            "article_number": "2",
            "text": "Bitiş.",
            "source_span": {"char_start": second_start, "char_end": len(missing_middle)},
            **provenance,
        },
    ]
    coverage = compute_parsing_coverage(
        missing_middle,
        [(0, len(first)), (second_start, len(missing_middle))],
    )
    assert _quality_report_for_text(missing_middle, [legislation, *articles], coverage).decision == "REVIEW"


def test_release_guard_blocks_unapproved_and_blocked_versions(quality_db):
    """
    Release Guard Test:
    - Version with quality == BLOCK cannot be approved (raises exception)
    - Blocked version cannot be selected for release
    """
    conn = get_connection()
    doc_id = "tr:legislation:law:9999"
    upsert_source(conn, "mevzuat", "Mevzuat", "Gov", "https://mevzuat.gov.tr")
    upsert_document(conn, doc_id, "legislation", "law", "TR", "9999 Sayılı Kanun", "stable-9999", "fetched")

    # Create raw artifact containing a blocker issue (valid TCKN checksum that triggers privacy blocker)
    content_corrupt = (
        "<!DOCTYPE html><html><body><h1>MADDE 1</h1><p>TCKN: 10000000146 gizli sahis verisi.</p></body></html>"
    )
    raw_dir = quality_db / "raw" / "legislation" / "mevzuat" / "2026"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "blocked_privacy.html"
    raw_bytes = content_corrupt.encode("utf-8")
    raw_file.write_bytes(raw_bytes)
    sha = hashlib.sha256(raw_bytes).hexdigest()
    art_id = f"art-{sha[:12]}"

    insert_artifact(
        conn,
        art_id,
        doc_id,
        "mevzuat",
        "https://example.com/blocked_privacy.html",
        "2026-08-01T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(raw_bytes),
        sha,
        str(raw_file.relative_to(quality_db)),
        None,
        None,
        "fetched",
        None,
        json.dumps({"publication_date": "2026-08-01"}),
    )
    conn.close()

    pipeline_status = process_artifact_pipeline(artifact_id=art_id, document_id=doc_id)
    assert pipeline_status == "rejected"

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id, quality_status, validation_status FROM versions WHERE document_id = ?", (doc_id,))
    v_row = c.fetchone()
    assert v_row is not None
    v_id, q_status, val_status = v_row
    assert q_status == "BLOCK"
    assert val_status == "failed"

    # Attempt to approve the BLOCKED version must raise BlockingValidationIssueExists
    with pytest.raises(BlockingValidationIssueExists):
        approve_version_streaming(conn, version_id=v_id, reviewer="operator-test")

    # Verify no records from this version are selectable for release
    recs_for_rel = list(iter_records_for_release(conn))
    assert len(recs_for_rel) == 0

    conn.close()
