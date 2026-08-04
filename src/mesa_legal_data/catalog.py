import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


@contextmanager
def transaction(conn: sqlite3.Connection):
    """
    Context manager for database transactions. Supports nesting safely.
    """
    if conn.in_transaction:
        yield conn
    else:
        conn.execute("BEGIN;")
        try:
            yield conn
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise


def hash_file(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        hasher.update(f.read())
    return hasher.hexdigest()


def migrate(migrations_dir: Path | None = None, db_path: Path | None = None):
    if migrations_dir is None:
        migrations_dir = Path(__file__).parent.parent.parent / "migrations"

    conn = get_connection(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            file_hash TEXT NOT NULL
        );
    """)

    cursor = conn.cursor()
    migration_files = sorted(migrations_dir.glob("*.sql"))

    for filepath in migration_files:
        version = filepath.name
        file_hash = hash_file(filepath)

        cursor.execute("SELECT file_hash FROM schema_migrations WHERE version = ?", (version,))
        row = cursor.fetchone()

        if row:
            stored_hash = row[0]
            if stored_hash != file_hash:
                conn.close()
                raise CatalogError(f"Migration hash mismatch for {version}")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            sql = f.read()

        try:
            conn.executescript("BEGIN;" + sql)
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at, file_hash) VALUES (?, ?, ?)",
                (version, now, file_hash),
            )
            conn.execute("COMMIT;")
        except Exception as e:
            conn.execute("ROLLBACK;")
            conn.close()
            raise CatalogError(f"Failed to apply migration {version}: {e}") from e

    # Check table existence before querying sources table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
    if cursor.fetchone():
        cursor.execute("SELECT count(*) FROM sources")
        if cursor.fetchone()[0] == 0:
            import yaml  # type: ignore[import-untyped]

            sources_yaml_path = Path(__file__).parent.parent.parent / "config" / "sources.yaml"
            if sources_yaml_path.exists():
                with open(sources_yaml_path, "r", encoding="utf-8") as f:
                    sources_data = yaml.safe_load(f).get("sources", {})
                now = datetime.now(UTC).isoformat()
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
                        ),
                    )

    conn.close()


# Repository Methods


def create_run(
    conn: sqlite3.Connection,
    run_id: str,
    command: str,
    source_id: str | None,
    code_version: str,
    config_sha256: str,
    input_json: str,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO processing_runs 
               (run_id, command, source_id, status, started_at, code_version, config_sha256, input_json, counters_json)
               VALUES (?, ?, ?, 'running', ?, ?, ?, ?, '{}')""",
            (run_id, command, source_id, now, code_version, config_sha256, input_json),
        )


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    counters_json: str,
    error_summary: str | None = None,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """UPDATE processing_runs 
               SET status = ?, finished_at = ?, counters_json = ?, error_summary = ? 
               WHERE run_id = ?""",
            (status, now, counters_json, error_summary, run_id),
        )


def upsert_document(
    conn: sqlite3.Connection,
    document_id: str,
    family: str,
    document_type: str,
    jurisdiction: str,
    title: str | None,
    stable_key: str,
    lifecycle_status: str,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(document_id) DO UPDATE SET
               title = excluded.title,
               lifecycle_status = excluded.lifecycle_status,
               updated_at = excluded.updated_at""",
            (
                document_id,
                family,
                document_type,
                jurisdiction,
                title,
                stable_key,
                lifecycle_status,
                now,
                now,
            ),
        )


def get_document(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, current_version_id, created_at, updated_at FROM documents WHERE document_id = ?",
        (document_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "document_id": row[0],
        "family": row[1],
        "document_type": row[2],
        "jurisdiction": row[3],
        "title": row[4],
        "stable_key": row[5],
        "lifecycle_status": row[6],
        "current_version_id": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def update_document_status(
    conn: sqlite3.Connection,
    document_id: str,
    status: str,
    current_version_id: str | None = None,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        if current_version_id:
            conn.execute(
                "UPDATE documents SET lifecycle_status = ?, current_version_id = ?, updated_at = ? WHERE document_id = ?",
                (status, current_version_id, now, document_id),
            )
        else:
            conn.execute(
                "UPDATE documents SET lifecycle_status = ?, updated_at = ? WHERE document_id = ?",
                (status, now, document_id),
            )


def insert_artifact(
    conn: sqlite3.Connection,
    artifact_id: str,
    document_id: str | None,
    source_id: str,
    source_url: str,
    retrieved_at: str,
    fetch_method: str,
    http_status: int | None,
    declared_content_type: str | None,
    detected_content_type: str,
    byte_size: int,
    sha256: str,
    raw_path: str,
    etag: str | None,
    last_modified: str | None,
    transport_status: str,
    error_code: str | None,
    metadata_json: str,
):
    with transaction(conn):
        conn.execute(
            """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, etag, last_modified, transport_status, error_code, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                document_id,
                source_id,
                source_url,
                retrieved_at,
                fetch_method,
                http_status,
                declared_content_type,
                detected_content_type,
                byte_size,
                sha256,
                raw_path,
                etag,
                last_modified,
                transport_status,
                error_code,
                metadata_json,
            ),
        )


def get_artifact(conn: sqlite3.Connection, artifact_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, etag, last_modified, transport_status, error_code, metadata_json FROM artifacts WHERE artifact_id = ?",
        (artifact_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "artifact_id": row[0],
        "document_id": row[1],
        "source_id": row[2],
        "source_url": row[3],
        "retrieved_at": row[4],
        "fetch_method": row[5],
        "http_status": row[6],
        "declared_content_type": row[7],
        "detected_content_type": row[8],
        "byte_size": row[9],
        "sha256": row[10],
        "raw_path": row[11],
        "etag": row[12],
        "last_modified": row[13],
        "transport_status": row[14],
        "error_code": row[15],
        "metadata_json": row[16],
    }


def update_artifact_transport_status(
    conn: sqlite3.Connection,
    artifact_id: str,
    status: str,
    error_code: str | None = None,
):
    with transaction(conn):
        conn.execute(
            "UPDATE artifacts SET transport_status = ?, error_code = ? WHERE artifact_id = ?",
            (status, error_code, artifact_id),
        )


def insert_version(
    conn: sqlite3.Connection,
    version_id: str,
    document_id: str,
    artifact_id: str,
    version_kind: str,
    snapshot_date: str | None,
    effective_from: str | None,
    effective_to: str | None,
    canonical_path: str,
    canonical_line: int,
    canonical_sha256: str,
    parser_name: str,
    parser_version: str,
    schema_version: str,
    validation_status: str,
    privacy_status: str,
    approval_status: str,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, snapshot_date, effective_from, effective_to, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                version_id,
                document_id,
                artifact_id,
                version_kind,
                snapshot_date,
                effective_from,
                effective_to,
                canonical_path,
                canonical_line,
                canonical_sha256,
                parser_name,
                parser_version,
                schema_version,
                validation_status,
                privacy_status,
                approval_status,
                now,
            ),
        )


def get_version(conn: sqlite3.Connection, version_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT version_id, document_id, artifact_id, version_kind, snapshot_date, effective_from, effective_to, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at FROM versions WHERE version_id = ?",
        (version_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "version_id": row[0],
        "document_id": row[1],
        "artifact_id": row[2],
        "version_kind": row[3],
        "snapshot_date": row[4],
        "effective_from": row[5],
        "effective_to": row[6],
        "canonical_path": row[7],
        "canonical_line": row[8],
        "canonical_sha256": row[9],
        "parser_name": row[10],
        "parser_version": row[11],
        "schema_version": row[12],
        "validation_status": row[13],
        "privacy_status": row[14],
        "approval_status": row[15],
        "created_at": row[16],
    }


def insert_record(
    conn: sqlite3.Connection,
    record_id: str,
    version_id: str,
    record_type: str,
    canonical_path: str,
    canonical_line: int,
    record_sha256: str,
    validation_status: str,
    approval_status: str,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                version_id,
                record_type,
                canonical_path,
                canonical_line,
                record_sha256,
                validation_status,
                approval_status,
                now,
            ),
        )


def get_record(conn: sqlite3.Connection, record_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at FROM records WHERE record_id = ?",
        (record_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "record_id": row[0],
        "version_id": row[1],
        "record_type": row[2],
        "canonical_path": row[3],
        "canonical_line": row[4],
        "record_sha256": row[5],
        "validation_status": row[6],
        "approval_status": row[7],
        "created_at": row[8],
    }


def list_records_by_approval_status(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at FROM records WHERE approval_status = ?",
            (status,),
        )
    else:
        cursor.execute(
            "SELECT record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at FROM records"
        )
    rows = cursor.fetchall()
    return [
        {
            "record_id": r[0],
            "version_id": r[1],
            "record_type": r[2],
            "canonical_path": r[3],
            "canonical_line": r[4],
            "record_sha256": r[5],
            "validation_status": r[6],
            "approval_status": r[7],
            "created_at": r[8],
        }
        for r in rows
    ]


def list_records_for_release(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT r.record_id, r.version_id, r.record_type, r.canonical_path, r.canonical_line, r.record_sha256
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        WHERE r.approval_status = 'approved'
          AND r.validation_status = 'valid'
          AND v.validation_status = 'valid'
          AND v.privacy_status IN ('clean', 'approved')
        ORDER BY r.record_id ASC
        """
    )
    rows = cursor.fetchall()
    results = []
    for r in rows:
        results.append(
            {
                "record_id": r[0],
                "version_id": r[1],
                "record_type": r[2],
                "canonical_path": r[3],
                "canonical_line": r[4],
                "record_sha256": r[5],
            }
        )
    return results


def open_issue(
    conn: sqlite3.Connection,
    issue_id: str,
    subject_type: str,
    subject_id: str,
    severity: str,
    code: str,
    message: str,
    details_json: str,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO validation_issues (issue_id, subject_type, subject_id, severity, code, message, details_json, status, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (
                issue_id,
                subject_type,
                subject_id,
                severity,
                code,
                message,
                details_json,
                now,
            ),
        )


def list_open_blocking_issues(conn: sqlite3.Connection, subject_id: str | None = None) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    if subject_id:
        cursor.execute(
            "SELECT issue_id, subject_type, subject_id, severity, code, message FROM validation_issues WHERE status = 'open' AND severity IN ('blocker', 'error') AND subject_id = ?",
            (subject_id,),
        )
    else:
        cursor.execute(
            "SELECT issue_id, subject_type, subject_id, severity, code, message FROM validation_issues WHERE status = 'open' AND severity IN ('blocker', 'error')"
        )
    rows = cursor.fetchall()
    return [
        {
            "issue_id": r[0],
            "subject_type": r[1],
            "subject_id": r[2],
            "severity": r[3],
            "code": r[4],
            "message": r[5],
        }
        for r in rows
    ]


def resolve_issue(
    conn: sqlite3.Connection,
    issue_id: str,
    status: str,
    resolved_by: str,
    resolution_note: str | None = None,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """UPDATE validation_issues 
               SET status = ?, resolved_at = ?, resolved_by = ?, resolution_note = ? 
               WHERE issue_id = ?""",
            (status, now, resolved_by, resolution_note, issue_id),
        )


def add_record_review(
    conn: sqlite3.Connection,
    review_id: str,
    record_id: str,
    record_sha256: str,
    decision: str,
    reviewer: str,
    note: str | None = None,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO record_reviews (review_id, record_id, record_sha256, decision, reviewer, note, reviewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (review_id, record_id, record_sha256, decision, reviewer, note, now),
        )
        conn.execute(
            "UPDATE records SET approval_status = ? WHERE record_id = ? AND record_sha256 = ?",
            (decision, record_id, record_sha256),
        )


def approve_record_with_checks(
    conn: sqlite3.Connection, record_id: str, reviewer: str, note: str | None = None
) -> dict[str, Any]:
    rec = get_record(conn, record_id)
    if not rec:
        raise CatalogError(f"Record {record_id} not found")

    blockers = list_open_blocking_issues(conn, subject_id=record_id)
    if blockers:
        raise CatalogError(f"Cannot approve record {record_id}: open blocker issues exist: {blockers}")

    settings = load_settings()
    c_path = settings.data_root_path / rec["canonical_path"]
    if not c_path.exists():
        raise CatalogError(f"Canonical file missing: {c_path}")

    # Verify record SHA256 against line in canonical JSONL file
    with open(c_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    line_idx = rec["canonical_line"] - 1
    if line_idx < 0 or line_idx >= len(lines):
        raise CatalogError(f"Canonical line {rec['canonical_line']} out of bounds in {c_path}")

    target_line = lines[line_idx]
    actual_hash = hashlib.sha256(target_line.encode("utf-8")).hexdigest()
    if actual_hash.lower() != rec["record_sha256"].lower():
        raise CatalogError(f"Record hash mismatch for {record_id}: expected {rec['record_sha256']}, got {actual_hash}")

    review_id = f"rev-{uuid.uuid4().hex[:8]}"
    add_record_review(conn, review_id, record_id, rec["record_sha256"], "approved", reviewer, note)
    return {"status": "approved", "record_id": record_id, "review_id": review_id}


def approve_version_with_checks(
    conn: sqlite3.Connection, version_id: str, reviewer: str, note: str | None = None
) -> dict[str, Any]:
    ver = get_version(conn, version_id)
    if not ver:
        raise CatalogError(f"Version {version_id} not found")

    cursor = conn.cursor()
    cursor.execute("SELECT record_id FROM records WHERE version_id = ?", (version_id,))
    record_ids = [r[0] for r in cursor.fetchall()]

    approved_count = 0
    for r_id in record_ids:
        approve_record_with_checks(conn, r_id, reviewer, note)
        approved_count += 1

    with transaction(conn):
        conn.execute(
            "UPDATE versions SET approval_status = 'approved' WHERE version_id = ?",
            (version_id,),
        )
        conn.execute(
            "UPDATE documents SET lifecycle_status = 'approved' WHERE document_id = ?",
            (ver["document_id"],),
        )

    return {
        "status": "approved",
        "version_id": version_id,
        "approved_records": approved_count,
    }


def reject_record_with_checks(
    conn: sqlite3.Connection, record_id: str, reviewer: str, note: str | None = None
) -> dict[str, Any]:
    rec = get_record(conn, record_id)
    if not rec:
        raise CatalogError(f"Record {record_id} not found")

    review_id = f"rev-{uuid.uuid4().hex[:8]}"
    add_record_review(conn, review_id, record_id, rec["record_sha256"], "rejected", reviewer, note)
    return {"status": "rejected", "record_id": record_id, "review_id": review_id}


def get_latest_valid_review(conn: sqlite3.Connection, record_id: str, record_sha256: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        """SELECT review_id, record_id, record_sha256, decision, reviewer, note, reviewed_at 
           FROM record_reviews 
           WHERE record_id = ? AND record_sha256 = ? 
           ORDER BY reviewed_at DESC LIMIT 1""",
        (record_id, record_sha256),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "review_id": row[0],
        "record_id": row[1],
        "record_sha256": row[2],
        "decision": row[3],
        "reviewer": row[4],
        "note": row[5],
        "reviewed_at": row[6],
    }


def create_release(
    conn: sqlite3.Connection,
    release_id: str,
    release_path: str,
    status: str,
    schema_version: str,
    counts_json: str,
    source_snapshot_json: str,
    manifest_sha256: str | None = None,
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO releases (release_id, release_path, status, schema_version, created_at, counts_json, source_snapshot_json, manifest_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                release_id,
                release_path,
                status,
                schema_version,
                now,
                counts_json,
                source_snapshot_json,
                manifest_sha256,
            ),
        )


def mark_release_status(
    conn: sqlite3.Connection,
    release_id: str,
    status: str,
    published_at: str | None = None,
):
    with transaction(conn):
        if published_at:
            conn.execute(
                "UPDATE releases SET status = ?, published_at = ? WHERE release_id = ?",
                (status, published_at, release_id),
            )
        else:
            conn.execute(
                "UPDATE releases SET status = ? WHERE release_id = ?",
                (status, release_id),
            )


def add_release_item(conn: sqlite3.Connection, release_id: str, record_id: str, record_sha256: str):
    with transaction(conn):
        conn.execute(
            """INSERT INTO release_items (release_id, record_id, record_sha256)
               VALUES (?, ?, ?)""",
            (release_id, record_id, record_sha256),
        )


def record_mesa_import(
    conn: sqlite3.Connection,
    release_id: str,
    status: str,
    target_db_path: str,
    imported_at: str,
    record_counts_json: str,
    error_summary: str | None = None,
):
    with transaction(conn):
        conn.execute(
            """INSERT INTO mesa_imports (release_id, status, target_db_path, imported_at, record_counts_json, error_summary)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(release_id) DO UPDATE SET
               status = excluded.status,
               imported_at = excluded.imported_at,
               record_counts_json = excluded.record_counts_json,
               error_summary = excluded.error_summary""",
            (
                release_id,
                status,
                target_db_path,
                imported_at,
                record_counts_json,
                error_summary,
            ),
        )
