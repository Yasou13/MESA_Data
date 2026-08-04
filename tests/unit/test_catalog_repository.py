import sqlite3
from pathlib import Path
import json

import pytest

from mesa_legal_data.catalog import (
    migrate,
    create_run,
    finish_run,
    upsert_document,
    insert_artifact,
    insert_version,
    insert_record,
    open_issue,
    resolve_issue,
    create_release,
    add_release_item,
    CatalogError
)

@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test.sqlite"
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    migrate(migrations_dir, db_path)
    
    conn = sqlite3.connect(db_path)
    # Enable foreign keys for testing
    conn.execute("PRAGMA foreign_keys = ON;")
    
    # We must insert a source manually to satisfy foreign key constraints for artifact
    conn.execute("BEGIN;")
    conn.execute(
        "INSERT INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at) "
        "VALUES ('test_src', 'Test', 'Test Auth', 'http://test', 'manual', 1, '1.0', '{}', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"
    )
    conn.execute("COMMIT;")
    yield conn
    conn.close()

def test_run_lifecycle(db_conn):
    run_id = "run-123"
    create_run(db_conn, run_id, "test_cmd", "test_src", "v1", "hash123", "{}")
    
    cursor = db_conn.cursor()
    cursor.execute("SELECT status FROM processing_runs WHERE run_id = ?", (run_id,))
    assert cursor.fetchone()[0] == "running"
    
    finish_run(db_conn, run_id, "succeeded", '{"docs": 1}')
    cursor.execute("SELECT status, counters_json FROM processing_runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    assert row[0] == "succeeded"
    assert row[1] == '{"docs": 1}'

def test_upsert_document(db_conn):
    doc_id = "tr:legislation:law:1"
    upsert_document(db_conn, doc_id, "legislation", "law", "TR", "Law 1", "stable1", "active")
    
    cursor = db_conn.cursor()
    cursor.execute("SELECT title FROM documents WHERE document_id = ?", (doc_id,))
    assert cursor.fetchone()[0] == "Law 1"
    
    # Test upsert updates title
    upsert_document(db_conn, doc_id, "legislation", "law", "TR", "Law 1 Updated", "stable1", "active")
    cursor.execute("SELECT title FROM documents WHERE document_id = ?", (doc_id,))
    assert cursor.fetchone()[0] == "Law 1 Updated"

def test_artifact_and_version(db_conn):
    doc_id = "tr:doc:1"
    art_id = "sha256:art1"
    ver_id = "ver1"
    
    upsert_document(db_conn, doc_id, "legislation", "law", "TR", "Title", "stable2", "active")
    
    insert_artifact(db_conn, art_id, doc_id, "test_src", "http://test", "2026-08-05T00:00:00Z", "manual", 200, "text/html", "text/html", 100, "hashX", "path/to/raw", None, None, "verified", None, "{}")
    
    insert_version(db_conn, ver_id, doc_id, art_id, "kind1", None, None, None, "path/canon", 1, "hashY", "parser1", "v1", "v1", "valid", "clean", "approved")
    
    insert_record(db_conn, "rec1", ver_id, "article", "path/canon", 1, "hashZ", "valid", "approved")
    
    cursor = db_conn.cursor()
    cursor.execute("SELECT count(*) FROM versions WHERE version_id = ?", (ver_id,))
    assert cursor.fetchone()[0] == 1
    
    cursor.execute("SELECT count(*) FROM records WHERE record_id = 'rec1'")
    assert cursor.fetchone()[0] == 1

def test_issues(db_conn):
    issue_id = "iss1"
    open_issue(db_conn, issue_id, "document", "doc1", "warning", "CODE1", "Message", "{}")
    
    cursor = db_conn.cursor()
    cursor.execute("SELECT status FROM validation_issues WHERE issue_id = ?", (issue_id,))
    assert cursor.fetchone()[0] == "open"
    
    resolve_issue(db_conn, issue_id, "resolved", "yasin", "Fixed")
    cursor.execute("SELECT status, resolved_by FROM validation_issues WHERE issue_id = ?", (issue_id,))
    row = cursor.fetchone()
    assert row[0] == "resolved"
    assert row[1] == "yasin"

def test_release(db_conn):
    rel_id = "rel1"
    create_release(db_conn, rel_id, "path/to/rel", "building", "1.0", "{}", "{}")
    
    # Needs a record to satisfy FK
    doc_id = "tr:doc:rel"
    art_id = "sha256:rel"
    ver_id = "ver_rel"
    rec_id = "rec_rel"
    upsert_document(db_conn, doc_id, "legislation", "law", "TR", "T", "st", "active")
    insert_artifact(db_conn, art_id, doc_id, "test_src", "http", "2026", "manual", 200, "html", "html", 1, "h", "p", None, None, "v", None, "{}")
    insert_version(db_conn, ver_id, doc_id, art_id, "k", None, None, None, "p", 1, "h", "p", "v", "v", "v", "c", "a")
    insert_record(db_conn, rec_id, ver_id, "t", "p", 1, "h", "v", "a")
    
    add_release_item(db_conn, rel_id, rec_id, "hashA")
    
    cursor = db_conn.cursor()
    cursor.execute("SELECT count(*) FROM release_items WHERE release_id = ?", (rel_id,))
    assert cursor.fetchone()[0] == 1
