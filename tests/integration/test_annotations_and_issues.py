import json

import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    BlockingValidationIssueExists,
    add_record_annotation,
    approve_record_with_checks,
    delete_record_annotation,
    get_connection,
    get_db_path,
    list_open_blocking_issues,
    list_record_annotations,
    migrate,
    open_issue,
    resolve_issue,
)
from mesa_legal_data.web.app import create_app


def test_annotations_issues_and_quarantine(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc-q1', 'legislation', 'law', 'TR', 'Quarantine Law', 'key-q1', 'fetched', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art-q1', 'doc-q1', 'mevzuat', 'https://example.com/q1.html', '2026-08-05T00:00:00Z', 'manual', 200, 'text/html', 'text/html', 10, 'sha-q1', 'raw/q1.html', 'fetched', '{}')"""
    )
    c.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
           VALUES ('ver-q1', 'doc-q1', 'art-q1', 'snapshot', 'canonical/q1.jsonl', 1, 'sha-ver-q1', 'test_parser', '1.0', '1.0', 'valid', 'clean', 'pending', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('rec-q1', 'ver-q1', 'article', 'canonical/q1.jsonl', 1, 'sha-rec-q1', 'invalid', 'pending', '2026-08-05T00:00:00Z')"""
    )

    # 1. Add Annotation
    ann_id = add_record_annotation(
        conn,
        record_id="rec-q1",
        annotation_type="tag",
        namespace="mesa.qc",
        key="needs_verification",
        value_json=json.dumps({"reviewer": "annotator_1"}),
        created_by="annotator_1",
    )
    assert ann_id.startswith("ann-")

    anns = list_record_annotations(conn, record_id="rec-q1")
    assert len(anns) == 1

    delete_record_annotation(conn, ann_id)
    assert len(list_record_annotations(conn, record_id="rec-q1")) == 0

    issue_id = "iss-q1"
    open_issue(
        conn,
        issue_id=issue_id,
        subject_type="record",
        subject_id="rec-q1",
        severity="blocker",
        code="INVALID_STRUCTURE",
        message="Record HTML missing article header",
        details_json="{}",
    )
    assert issue_id.startswith("iss-")

    blockers = list_open_blocking_issues(conn, subject_id="rec-q1")
    assert len(blockers) >= 1

    # Attempt approval while blocker exists -> Quarantine / Rejected
    with pytest.raises(BlockingValidationIssueExists):
        approve_record_with_checks(conn, "rec-q1", reviewer="lead")

    # Resolve issue
    resolve_issue(conn, issue_id, status="resolved", resolved_by="lead", resolution_note="Fixed HTML structure")
    blockers_after = list_open_blocking_issues(conn, subject_id="rec-q1")
    assert len(blockers_after) == 0

    conn.close()

    # 3. HTTP Annotations API End-to-End (Removed -> 404)
    app = create_app()
    client = TestClient(app)

    headers = {"X-MESA-Requested-With": "web-admin", "X-MESA-Actor": "web_annotator"}
    res_post = client.post(
        "/api/records/rec-q1/annotations",
        json={"annotation_type": "note", "namespace": "test", "key": "note1", "value": "check law"},
        headers=headers,
    )
    assert res_post.status_code in (404, 405)
