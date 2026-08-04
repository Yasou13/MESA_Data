import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import json

from mesa_legal_data.config import load_settings


class CatalogError(Exception):
    pass


def get_db_path() -> Path:
    settings = load_settings()
    return settings.data_root_path / "catalog.sqlite"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = get_db_path()
        
    conn = sqlite3.connect(db_path, isolation_level=None)
    
    # Apply PRAGMA settings
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    
    return conn


def hash_file(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def migrate(migrations_dir: Path | None = None, db_path: Path | None = None):
    if migrations_dir is None:
        # Default to the 'migrations' directory at the project root
        migrations_dir = Path(__file__).parent.parent.parent / "migrations"
        
    conn = get_connection(db_path)
    
    # Create schema_migrations table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            file_hash TEXT NOT NULL
        );
    """)
    
    cursor = conn.cursor()
    
    # Get all migration files
    migration_files = sorted(list(migrations_dir.glob("*.sql")))
    
    for filepath in migration_files:
        version = filepath.name
        file_hash = hash_file(filepath)
        
        cursor.execute("SELECT file_hash FROM schema_migrations WHERE version = ?", (version,))
        row = cursor.fetchone()
        
        if row:
            stored_hash = row[0]
            if stored_hash != file_hash:
                raise CatalogError(f"Migration hash mismatch for {version}")
            # Already applied, skip
            continue
            
        # Apply migration
        with open(filepath, "r", encoding="utf-8") as f:
            sql = f.read()
            
        try:
            # executescript implicitly commits any pending transaction, 
            # so we just run it directly.
            conn.executescript("BEGIN;" + sql)
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at, file_hash) VALUES (?, ?, ?)",
                (version, now, file_hash)
            )
            conn.execute("COMMIT;")
        except Exception as e:
            conn.execute("ROLLBACK;")
            raise CatalogError(f"Failed to apply migration {version}: {e}") from e

    # Seed sources from sources.yaml if sources table is empty
    cursor.execute("SELECT count(*) FROM sources")
    if cursor.fetchone()[0] == 0:
        import yaml
        sources_yaml_path = Path(__file__).parent.parent.parent / "config" / "sources.yaml"
        if sources_yaml_path.exists():
            with open(sources_yaml_path, "r", encoding="utf-8") as f:
                sources_data = yaml.safe_load(f).get("sources", {})
            now = datetime.now(timezone.utc).isoformat()
            for s_id, s_info in sources_data.items():
                conn.execute(
                    """INSERT INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        s_id,
                        s_info.get("name", s_id),
                        s_info.get("authority", "Official"),
                        s_info.get("base_url", "http://example.com"),
                        s_info.get("access_mode", "manual"),
                        1 if s_info.get("enabled", True) else 0,
                        s_info.get("policy_version", "1.0.0"),
                        json.dumps(s_info),
                        now,
                        now,
                    )
                )

    conn.close()


# Repository Methods

def create_run(conn: sqlite3.Connection, run_id: str, command: str, source_id: str | None, code_version: str, config_sha256: str, input_json: str):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO processing_runs 
               (run_id, command, source_id, status, started_at, code_version, config_sha256, input_json, counters_json)
               VALUES (?, ?, ?, 'running', ?, ?, ?, ?, '{}')""",
            (run_id, command, source_id, now, code_version, config_sha256, input_json)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"create_run failed: {e}") from e

def finish_run(conn: sqlite3.Connection, run_id: str, status: str, counters_json: str, error_summary: str | None = None):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """UPDATE processing_runs 
               SET status = ?, finished_at = ?, counters_json = ?, error_summary = ? 
               WHERE run_id = ?""",
            (status, now, counters_json, error_summary, run_id)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"finish_run failed: {e}") from e

def upsert_document(conn: sqlite3.Connection, document_id: str, family: str, document_type: str, jurisdiction: str, title: str | None, stable_key: str, lifecycle_status: str):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(document_id) DO UPDATE SET
               title = excluded.title,
               lifecycle_status = excluded.lifecycle_status,
               updated_at = excluded.updated_at""",
            (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, now, now)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"upsert_document failed: {e}") from e

def insert_artifact(conn: sqlite3.Connection, artifact_id: str, document_id: str | None, source_id: str, source_url: str, retrieved_at: str, fetch_method: str, http_status: int | None, declared_content_type: str | None, detected_content_type: str, byte_size: int, sha256: str, raw_path: str, etag: str | None, last_modified: str | None, transport_status: str, error_code: str | None, metadata_json: str):
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, etag, last_modified, transport_status, error_code, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, etag, last_modified, transport_status, error_code, metadata_json)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"insert_artifact failed: {e}") from e

def insert_version(conn: sqlite3.Connection, version_id: str, document_id: str, artifact_id: str, version_kind: str, snapshot_date: str | None, effective_from: str | None, effective_to: str | None, canonical_path: str, canonical_line: int, canonical_sha256: str, parser_name: str, parser_version: str, schema_version: str, validation_status: str, privacy_status: str, approval_status: str):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, snapshot_date, effective_from, effective_to, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (version_id, document_id, artifact_id, version_kind, snapshot_date, effective_from, effective_to, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, now)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"insert_version failed: {e}") from e

def insert_record(conn: sqlite3.Connection, record_id: str, version_id: str, record_type: str, canonical_path: str, canonical_line: int, record_sha256: str, validation_status: str, approval_status: str):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, now)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"insert_record failed: {e}") from e

def open_issue(conn: sqlite3.Connection, issue_id: str, subject_type: str, subject_id: str, severity: str, code: str, message: str, details_json: str):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO validation_issues (issue_id, subject_type, subject_id, severity, code, message, details_json, status, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (issue_id, subject_type, subject_id, severity, code, message, details_json, now)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"open_issue failed: {e}") from e

def resolve_issue(conn: sqlite3.Connection, issue_id: str, status: str, resolved_by: str, resolution_note: str | None = None):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """UPDATE validation_issues 
               SET status = ?, resolved_at = ?, resolved_by = ?, resolution_note = ? 
               WHERE issue_id = ?""",
            (status, now, resolved_by, resolution_note, issue_id)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"resolve_issue failed: {e}") from e

def create_release(conn: sqlite3.Connection, release_id: str, release_path: str, status: str, schema_version: str, counts_json: str, source_snapshot_json: str, manifest_sha256: str | None = None):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO releases (release_id, release_path, status, schema_version, created_at, counts_json, source_snapshot_json, manifest_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (release_id, release_path, status, schema_version, now, counts_json, source_snapshot_json, manifest_sha256)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"create_release failed: {e}") from e

def add_release_item(conn: sqlite3.Connection, release_id: str, record_id: str, record_sha256: str):
    conn.execute("BEGIN;")
    try:
        conn.execute(
            """INSERT INTO release_items (release_id, record_id, record_sha256)
               VALUES (?, ?, ?)""",
            (release_id, record_id, record_sha256)
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise CatalogError(f"add_release_item failed: {e}") from e
