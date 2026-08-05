import json
import pytest

from mesa_legal_data.catalog import (
    approve_record_revision,
    create_record_revision,
    get_connection,
    get_db_path,
    get_record,
    get_record_revision,
    list_record_revisions,
    migrate,
    reject_record_revision,
)


def test_record_revision_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc-rev-1', 'legislation', 'law', 'TR', 'Rev Law', 'key-rev-1', 'fetched', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art-rev-1', 'doc-rev-1', 'mevzuat', 'https://example.com/rev.html', '2026-08-05T00:00:00Z', 'manual', 200, 'text/html', 'text/html', 10, 'sha-rev-1', 'raw/rev.html', 'fetched', '{}')"""
    )
    c.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
           VALUES ('ver-rev-1', 'doc-rev-1', 'art-rev-1', 'snapshot', 'canonical/rev.jsonl', 1, 'sha-ver-rev-1', 'test_parser', '1.0', '1.0', 'valid', 'clean', 'pending', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('rec-orig-1', 'ver-rev-1', 'article', 'canonical/rev.jsonl', 1, 'sha-rec-orig-1', 'valid', 'pending', '2026-08-05T00:00:00Z')"""
    )
    conn.commit()

    # 1. Create revision draft
    rev_id = create_record_revision(
        conn,
        original_record_id="rec-orig-1",
        original_record_sha256="sha-rec-orig-1",
        revised_record_id="rec-orig-1",
        revised_record_sha256="sha-rec-rev-1",
        version_id="ver-rev-1",
        change_type="typo_fix",
        patch_json=json.dumps({"op": "replace", "path": "/title", "value": "Corrected Title"}),
        reason="Typo in law text",
        created_by="editor_1",
    )
    assert rev_id.startswith("rev-")

    rev_obj = get_record_revision(conn, rev_id)
    assert rev_obj["status"] == "draft"
    assert rev_obj["change_type"] == "typo_fix"

    rev_list = list_record_revisions(conn, record_id="rec-orig-1")
    assert len(rev_list) >= 1

    # 2. Approve revision -> Status approved, updates record
    app_res = approve_record_revision(conn, rev_id, reviewer="lead_editor", note="LGTM")
    assert app_res["status"] == "approved"

    rec_after = get_record(conn, "rec-orig-1")
    assert rec_after["approval_status"] == "approved"

    # 3. Reject another revision
    rev_id2 = create_record_revision(
        conn,
        original_record_id="rec-orig-1",
        original_record_sha256="sha-rec-orig-1",
        revised_record_id="rec-orig-1",
        revised_record_sha256="sha-rec-rev-2",
        version_id="ver-rev-1",
        change_type="illegal_change",
        patch_json="{}",
        reason="Invalid patch",
        created_by="editor_2",
    )
    rej_res = reject_record_revision(conn, rev_id2, reviewer="lead_editor", reason="Rejected")
    assert rej_res["status"] == "rejected"

    conn.close()
