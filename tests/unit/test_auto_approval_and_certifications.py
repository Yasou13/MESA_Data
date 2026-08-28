import pytest

from mesa_legal_data.catalog import (
    evaluate_auto_approval,
    get_connection,
    get_version,
    insert_artifact,
    insert_version,
    migrate,
    set_parser_certification,
    upsert_document,
    upsert_source_operational_settings,
)


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test_catalog.sqlite"
    migrate(None, db_path)
    conn = get_connection(db_path)
    upsert_document(
        conn,
        document_id="doc-test-1",
        family="legislation",
        document_type="law",
        jurisdiction="TR",
        title="Test Kanun",
        stable_key="doc-test-1-key",
        lifecycle_status="fetched",
    )
    insert_artifact(
        conn=conn,
        artifact_id="art-test-1",
        document_id="doc-test-1",
        source_id="resmi_gazete",
        source_url="https://resmigazete.gov.tr/test.html",
        retrieved_at="2026-08-28T12:00:00Z",
        fetch_method="http",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=1024,
        sha256="1111222233334444555566667777888899990000111122223333444455556666",
        raw_path="raw/resmi_gazete/test.html",
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    yield conn
    conn.close()


def _add_version(
    conn, version_id, revision_number=1, quality_status="PASS", validation_status="valid", parser_version="1.0.0"
):
    insert_version(
        conn=conn,
        version_id=version_id,
        document_id="doc-test-1",
        artifact_id="art-test-1",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path="canonical/test.jsonl",
        canonical_line=1,
        canonical_sha256="2222222222222222222222222222222222222222222222222222222222222222",
        parser_name="resmi_gazete_parser",
        parser_version=parser_version,
        schema_version="1.0.0",
        validation_status=validation_status,
        privacy_status="clean",
        approval_status="pending",
        revision_number=revision_number,
        quality_status=quality_status,
    )


def test_auto_approval_happy_path_certified_pass(db_conn):
    upsert_source_operational_settings(
        db_conn, source_id="resmi_gazete", enabled=True, auto_approval_enabled=True, weekly_sample_count=0
    )
    set_parser_certification(
        db_conn, source_id="resmi_gazete", parser_name="resmi_gazete_parser", parser_version="1.0.0", certified=True
    )

    _add_version(db_conn, "doc-test-1:v1", revision_number=1, quality_status="PASS", validation_status="valid")

    approved, reason = evaluate_auto_approval(
        conn=db_conn,
        version_id="doc-test-1:v1",
        source_id="resmi_gazete",
        parser_name="resmi_gazete_parser",
        parser_version="1.0.0",
        quality_decision="PASS",
        has_privacy_blocker=False,
        schema_valid=True,
    )

    assert approved is True
    assert "Auto-approved" in reason

    v = get_version(db_conn, "doc-test-1:v1")
    assert v is not None
    assert v["approval_status"] == "approved"
    assert v["auto_approved"] == 1
    assert v["is_audit_sample"] == 0


def test_auto_approval_uncertified_parser_stays_in_review(db_conn):
    upsert_source_operational_settings(
        db_conn, source_id="resmi_gazete", enabled=True, auto_approval_enabled=True, weekly_sample_count=0
    )
    set_parser_certification(
        db_conn, source_id="resmi_gazete", parser_name="resmi_gazete_parser", parser_version="2.0.0", certified=False
    )

    _add_version(
        db_conn,
        "doc-test-1:v2",
        revision_number=2,
        quality_status="PASS",
        validation_status="valid",
        parser_version="2.0.0",
    )

    approved, reason = evaluate_auto_approval(
        conn=db_conn,
        version_id="doc-test-1:v2",
        source_id="resmi_gazete",
        parser_name="resmi_gazete_parser",
        parser_version="2.0.0",
        quality_decision="PASS",
        has_privacy_blocker=False,
        schema_valid=True,
    )

    assert approved is False
    assert "not certified" in reason

    v = get_version(db_conn, "doc-test-1:v2")
    assert v is not None
    assert v["approval_status"] == "pending"
    assert v["auto_approved"] == 0


def test_auto_approval_audit_sample_routes_to_review(db_conn):
    upsert_source_operational_settings(
        db_conn, source_id="resmi_gazete", enabled=True, auto_approval_enabled=True, weekly_sample_count=100
    )
    set_parser_certification(
        db_conn, source_id="resmi_gazete", parser_name="resmi_gazete_parser", parser_version="1.0.0", certified=True
    )

    _add_version(db_conn, "doc-test-1:v3", revision_number=3, quality_status="PASS", validation_status="valid")

    approved, reason = evaluate_auto_approval(
        conn=db_conn,
        version_id="doc-test-1:v3",
        source_id="resmi_gazete",
        parser_name="resmi_gazete_parser",
        parser_version="1.0.0",
        quality_decision="PASS",
        has_privacy_blocker=False,
        schema_valid=True,
    )

    assert approved is False
    assert "audit" in reason

    v = get_version(db_conn, "doc-test-1:v3")
    assert v is not None
    assert v["approval_status"] == "pending"
    assert v["is_audit_sample"] == 1
    assert v["audit_sample_reason"] == "quality_audit_sample"
    assert v["auto_approved"] == 0


def test_auto_approval_blocked_quality_never_approved(db_conn):
    upsert_source_operational_settings(
        db_conn, source_id="resmi_gazete", enabled=True, auto_approval_enabled=True, weekly_sample_count=0
    )
    set_parser_certification(
        db_conn, source_id="resmi_gazete", parser_name="resmi_gazete_parser", parser_version="1.0.0", certified=True
    )

    _add_version(db_conn, "doc-test-1:v4", revision_number=4, quality_status="BLOCK", validation_status="failed")

    approved, reason = evaluate_auto_approval(
        conn=db_conn,
        version_id="doc-test-1:v4",
        source_id="resmi_gazete",
        parser_name="resmi_gazete_parser",
        parser_version="1.0.0",
        quality_decision="BLOCK",
        has_privacy_blocker=False,
        schema_valid=False,
    )

    assert approved is False
    assert "BLOCK" in reason

    v = get_version(db_conn, "doc-test-1:v4")
    assert v is not None
    assert v["approval_status"] == "pending"
    assert v["auto_approved"] == 0


def test_auto_approval_privacy_blocker_stops_approval(db_conn):
    upsert_source_operational_settings(
        db_conn, source_id="resmi_gazete", enabled=True, auto_approval_enabled=True, weekly_sample_count=0
    )
    set_parser_certification(
        db_conn, source_id="resmi_gazete", parser_name="resmi_gazete_parser", parser_version="1.0.0", certified=True
    )

    _add_version(db_conn, "doc-test-1:v5", revision_number=5, quality_status="PASS", validation_status="valid")

    approved, reason = evaluate_auto_approval(
        conn=db_conn,
        version_id="doc-test-1:v5",
        source_id="resmi_gazete",
        parser_name="resmi_gazete_parser",
        parser_version="1.0.0",
        quality_decision="PASS",
        has_privacy_blocker=True,
        schema_valid=True,
    )

    assert approved is False
    assert "Privacy" in reason
