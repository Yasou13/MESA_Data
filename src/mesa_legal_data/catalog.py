import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(version_id) DO UPDATE SET
                   document_id = excluded.document_id,
                   artifact_id = excluded.artifact_id,
                   version_kind = excluded.version_kind,
                   canonical_path = excluded.canonical_path,
                   canonical_line = excluded.canonical_line,
                   canonical_sha256 = excluded.canonical_sha256,
                   parser_name = excluded.parser_name,
                   parser_version = excluded.parser_version,
                   schema_version = excluded.schema_version,
                   validation_status = excluded.validation_status,
                   privacy_status = excluded.privacy_status,
                   approval_status = excluded.approval_status""",
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
    validation_status: str = "valid",
    approval_status: str = "pending",
):
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(record_id) DO UPDATE SET
                   version_id = excluded.version_id,
                   record_type = excluded.record_type,
                   canonical_path = excluded.canonical_path,
                   canonical_line = excluded.canonical_line,
                   record_sha256 = excluded.record_sha256,
                   validation_status = excluded.validation_status,
                   approval_status = excluded.approval_status""",
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
    rows = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        rows.extend(batch)
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


@dataclass(frozen=True)
class ReleaseRecordRef:
    record_id: str
    record_type: str
    record_sha256: str
    canonical_path: str
    canonical_line: int
    version_id: str


def iter_records_for_release(
    conn: sqlite3.Connection,
    *,
    batch_size: int = 1000,
) -> Iterator[ReleaseRecordRef]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT r.record_id, r.record_type, r.record_sha256, r.canonical_path, r.canonical_line, r.version_id
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        WHERE r.approval_status = 'approved'
          AND r.validation_status = 'valid'
          AND v.validation_status = 'valid'
          AND v.privacy_status IN ('clean', 'approved')
        ORDER BY r.canonical_path ASC, r.canonical_line ASC
        """
    )
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for r in rows:
            yield ReleaseRecordRef(
                record_id=r[0],
                record_type=r[1],
                record_sha256=r[2],
                canonical_path=r[3],
                canonical_line=r[4],
                version_id=r[5],
            )


def list_records_for_release(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "record_id": ref.record_id,
            "version_id": ref.version_id,
            "record_type": ref.record_type,
            "canonical_path": ref.canonical_path,
            "canonical_line": ref.canonical_line,
            "record_sha256": ref.record_sha256,
        }
        for ref in iter_records_for_release(conn)
    ]


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
    rows = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        rows.extend(batch)
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
    target_line = None
    target_idx = rec["canonical_line"]
    with open(c_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if idx == target_idx:
                target_line = line
                break

    if target_line is None:
        raise CatalogError(f"Canonical line {rec['canonical_line']} out of bounds in {c_path}")

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
    record_ids = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        record_ids.extend([r[0] for r in batch])

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


def approve_version_streaming(
    conn: sqlite3.Connection,
    *,
    version_id: str,
    reviewer: str,
    note: str | None = None,
    batch_size: int = 2000,
) -> dict[str, Any]:
    ver = get_version(conn, version_id)
    if not ver:
        raise CatalogError(f"Version {version_id} not found")

    blockers = list_open_blocking_issues(conn, subject_id=version_id)
    if blockers:
        raise BlockingValidationIssueExists(
            f"Cannot approve version {version_id}: open blocking issues exist: {blockers}"
        )

    data_root = load_settings().data_root_path

    # Temp SQLite table to index records by canonical_path and canonical_line
    spool_db_path = data_root / f".approve_spool-{uuid.uuid4().hex[:8]}.sqlite"
    spool_conn = sqlite3.connect(spool_db_path)
    spool_conn.executescript("""
        CREATE TABLE version_records (
            record_id TEXT NOT NULL,
            canonical_path TEXT NOT NULL,
            canonical_line INTEGER NOT NULL,
            record_sha256 TEXT NOT NULL,
            PRIMARY KEY (canonical_path, canonical_line)
        );
    """)

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT record_id, canonical_path, canonical_line, record_sha256 FROM records WHERE version_id = ? ORDER BY canonical_path ASC, canonical_line ASC",
            (version_id,),
        )

        record_batch = []
        total_records = 0
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            for r in rows:
                record_batch.append((r[0], r[1], r[2], r[3]))
                total_records += 1
                if len(record_batch) >= batch_size:
                    spool_conn.executemany(
                        "INSERT INTO version_records (record_id, canonical_path, canonical_line, record_sha256) VALUES (?, ?, ?, ?)",
                        record_batch,
                    )
                    record_batch.clear()

        if record_batch:
            spool_conn.executemany(
                "INSERT INTO version_records (record_id, canonical_path, canonical_line, record_sha256) VALUES (?, ?, ?, ?)",
                record_batch,
            )
            record_batch.clear()

        spool_conn.commit()

        if total_records == 0:
            spool_conn.close()
            if spool_db_path.exists():
                spool_db_path.unlink()
            return {"version_id": version_id, "approved_records": 0, "approval_status": "approved"}

        # Get distinct canonical paths
        p_cur = spool_conn.cursor()
        p_cur.execute("SELECT DISTINCT canonical_path FROM version_records ORDER BY canonical_path ASC")
        c_paths = []
        while True:
            rows = p_cur.fetchmany(1000)
            if not rows:
                break
            c_paths.extend([r[0] for r in rows])

        approved_record_ids = []
        review_entries = []
        now_iso = datetime.now(UTC).isoformat()

        # O(n) Single Sequential Pass over Canonical Files
        for rel_c_path in c_paths:
            abs_c_path = data_root / rel_c_path
            if not abs_c_path.exists():
                raise CatalogError(f"Canonical file missing: {abs_c_path}")

            line_cur = spool_conn.cursor()
            line_cur.execute(
                "SELECT canonical_line, record_id, record_sha256 FROM version_records WHERE canonical_path = ? ORDER BY canonical_line ASC",
                (rel_c_path,),
            )

            with open(abs_c_path, "r", encoding="utf-8") as f:
                target = line_cur.fetchone()
                for idx, line in enumerate(f, start=1):
                    while target and target[0] == idx:
                        target_line_num, r_id, expected_hash = target

                        calc_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()
                        if calc_hash.lower() != expected_hash.lower():
                            raise CatalogError(
                                f"Record SHA256 mismatch for {r_id}: expected {expected_hash}, got {calc_hash}"
                            )

                        approved_record_ids.append(r_id)
                        review_entries.append((r_id, expected_hash, reviewer, "approved", note, now_iso))

                        target = line_cur.fetchone()

                    if not target:
                        break

                if target:
                    raise CatalogError(f"Canonical line {target[0]} out of bounds in {abs_c_path}")

        spool_conn.close()
        if spool_db_path.exists():
            spool_db_path.unlink()

        # Perform atomic batch approval in single transaction
        with transaction(conn):
            # Insert record_reviews in batches
            for i in range(0, len(review_entries), batch_size):
                chunk = review_entries[i : i + batch_size]
                conn.executemany(
                    "INSERT INTO record_reviews (record_id, record_sha256, reviewer, decision, note, reviewed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    chunk,
                )

            # Update records status in batches
            id_tuples = [(r_id,) for r_id in approved_record_ids]
            for i in range(0, len(id_tuples), batch_size):
                chunk = id_tuples[i : i + batch_size]
                conn.executemany(
                    "UPDATE records SET approval_status = 'approved' WHERE record_id = ?",
                    chunk,
                )

            conn.execute(
                "UPDATE versions SET approval_status = 'approved' WHERE version_id = ?",
                (version_id,),
            )
            conn.execute(
                "UPDATE documents SET lifecycle_status = 'approved', updated_at = ? WHERE document_id = ?",
                (now_iso, ver["document_id"]),
            )

        log_audit_event(
            conn,
            actor=reviewer,
            action="version_approve",
            subject_type="version",
            subject_id=version_id,
            reason=note,
            details_json=json.dumps({"approved_records": len(approved_record_ids)}),
        )

        return {"version_id": version_id, "approved_records": len(approved_record_ids), "approval_status": "approved"}

    except Exception:
        spool_conn.close()
        if spool_db_path.exists():
            try:
                spool_db_path.unlink()
            except OSError:
                pass
        raise


def upsert_source(
    conn: sqlite3.Connection,
    source_id: str,
    name: str,
    authority: str,
    base_url: str,
    access_mode: str = "manual",
    enabled: int = 1,
    policy_version: str = "1.0.0",
    config_json: str = "{}",
) -> None:
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name = excluded.name,
                authority = excluded.authority,
                base_url = excluded.base_url,
                access_mode = excluded.access_mode,
                enabled = excluded.enabled,
                policy_version = excluded.policy_version,
                config_json = excluded.config_json,
                updated_at = excluded.updated_at
            """,
            (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, now, now),
        )


# --- AUDIT EVENTS ---

def log_audit_event(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    reason: str | None = None,
    old_sha256: str | None = None,
    new_sha256: str | None = None,
    details_json: str = "{}",
    request_id: str | None = None,
    event_id: str | None = None,
) -> str:
    if not event_id:
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO audit_events (event_id, actor, action, subject_type, subject_id, old_sha256, new_sha256, reason, details_json, request_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                actor,
                action,
                subject_type,
                subject_id,
                old_sha256,
                new_sha256,
                reason,
                details_json,
                request_id,
                now,
            ),
        )
    return event_id


def list_audit_events(
    conn: sqlite3.Connection,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = "SELECT event_id, actor, action, subject_type, subject_id, old_sha256, new_sha256, reason, details_json, request_id, created_at FROM audit_events WHERE 1=1"
    params: list[Any] = []
    if subject_type:
        query += " AND subject_type = ?"
        params.append(subject_type)
    if subject_id:
        query += " AND subject_id = ?"
        params.append(subject_id)
    if action:
        query += " AND action = ?"
        params.append(action)
    if actor:
        query += " AND actor = ?"
        params.append(actor)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = conn.cursor()
    cursor.execute(query, tuple(params))
    rows = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        rows.extend(batch)
    return [
        {
            "event_id": r[0],
            "actor": r[1],
            "action": r[2],
            "subject_type": r[3],
            "subject_id": r[4],
            "old_sha256": r[5],
            "new_sha256": r[6],
            "reason": r[7],
            "details_json": r[8],
            "request_id": r[9],
            "created_at": r[10],
        }
        for r in rows
    ]


# --- RECORD ANNOTATIONS ---

def add_record_annotation(
    conn: sqlite3.Connection,
    *,
    record_id: str,
    annotation_type: str,
    namespace: str,
    key: str,
    value_json: str,
    created_by: str,
    annotation_id: str | None = None,
) -> str:
    if not annotation_id:
        annotation_id = f"ann-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO record_annotations (annotation_id, record_id, annotation_type, namespace, key, value_json, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                annotation_id,
                record_id,
                annotation_type,
                namespace,
                key,
                value_json,
                created_by,
                now,
                now,
            ),
        )
    return annotation_id


def list_record_annotations(conn: sqlite3.Connection, record_id: str) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT annotation_id, record_id, annotation_type, namespace, key, value_json, created_by, created_at, updated_at FROM record_annotations WHERE record_id = ? ORDER BY created_at ASC",
        (record_id,),
    )
    rows = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        rows.extend(batch)
    return [
        {
            "annotation_id": r[0],
            "record_id": r[1],
            "annotation_type": r[2],
            "namespace": r[3],
            "key": r[4],
            "value_json": r[5],
            "created_by": r[6],
            "created_at": r[7],
            "updated_at": r[8],
        }
        for r in rows
    ]


def delete_record_annotation(conn: sqlite3.Connection, annotation_id: str):
    with transaction(conn):
        conn.execute("DELETE FROM record_annotations WHERE annotation_id = ?", (annotation_id,))


# --- RECORD REVISIONS ---

def create_record_revision(
    conn: sqlite3.Connection,
    *,
    original_record_id: str,
    original_record_sha256: str,
    revised_record_id: str,
    revised_record_sha256: str,
    version_id: str,
    change_type: str,
    patch_json: str,
    reason: str,
    created_by: str,
    status: str = "draft",
    revision_id: str | None = None,
) -> str:
    if not revision_id:
        revision_id = f"rev-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO record_revisions (revision_id, original_record_id, original_record_sha256, revised_record_id, revised_record_sha256, version_id, change_type, patch_json, reason, created_by, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                revision_id,
                original_record_id,
                original_record_sha256,
                revised_record_id,
                revised_record_sha256,
                version_id,
                change_type,
                patch_json,
                reason,
                created_by,
                now,
                status,
            ),
        )
    return revision_id


def get_record_revision(conn: sqlite3.Connection, revision_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT revision_id, original_record_id, original_record_sha256, revised_record_id, revised_record_sha256, version_id, change_type, patch_json, reason, created_by, created_at, status FROM record_revisions WHERE revision_id = ?",
        (revision_id,),
    )
    r = cursor.fetchone()
    if not r:
        return None
    return {
        "revision_id": r[0],
        "original_record_id": r[1],
        "original_record_sha256": r[2],
        "revised_record_id": r[3],
        "revised_record_sha256": r[4],
        "version_id": r[5],
        "change_type": r[6],
        "patch_json": r[7],
        "reason": r[8],
        "created_by": r[9],
        "created_at": r[10],
        "status": r[11],
    }


def update_record_revision_status(conn: sqlite3.Connection, revision_id: str, status: str):
    with transaction(conn):
        conn.execute("UPDATE record_revisions SET status = ? WHERE revision_id = ?", (status, revision_id))


# --- SOURCE CONFIG REVISIONS ---

def create_source_config_revision(
    conn: sqlite3.Connection,
    *,
    config_sha256: str,
    content_yaml: str,
    reason: str,
    created_by: str,
    status: str = "draft",
    validation_json: str = "{}",
    revision_id: str | None = None,
) -> str:
    if not revision_id:
        revision_id = f"cfgrev-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO source_config_revisions (revision_id, config_sha256, content_yaml, reason, created_by, created_at, status, validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                revision_id,
                config_sha256,
                content_yaml,
                reason,
                created_by,
                now,
                status,
                validation_json,
            ),
        )
    return revision_id


def get_source_config_revision(conn: sqlite3.Connection, revision_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT revision_id, config_sha256, content_yaml, reason, created_by, created_at, status, validation_json FROM source_config_revisions WHERE revision_id = ?",
        (revision_id,),
    )
    r = cursor.fetchone()
    if not r:
        return None
    return {
        "revision_id": r[0],
        "config_sha256": r[1],
        "content_yaml": r[2],
        "reason": r[3],
        "created_by": r[4],
        "created_at": r[5],
        "status": r[6],
        "validation_json": r[7],
    }


def list_source_config_revisions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT revision_id, config_sha256, content_yaml, reason, created_by, created_at, status, validation_json FROM source_config_revisions ORDER BY created_at DESC"
    )
    rows = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        rows.extend(batch)
    return [
        {
            "revision_id": r[0],
            "config_sha256": r[1],
            "content_yaml": r[2],
            "reason": r[3],
            "created_by": r[4],
            "created_at": r[5],
            "status": r[6],
            "validation_json": r[7],
        }
        for r in rows
    ]


def update_source_config_revision_status(conn: sqlite3.Connection, revision_id: str, status: str):
    with transaction(conn):
        conn.execute("UPDATE source_config_revisions SET status = ? WHERE revision_id = ?", (status, revision_id))


# --- OPERATION JOBS ---

def create_operation_job(
    conn: sqlite3.Connection,
    *,
    operation_type: str,
    requested_by: str,
    input_json: str,
    progress_total: int | None = None,
    operation_id: str | None = None,
) -> str:
    if not operation_id:
        operation_id = f"op-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO operation_jobs (operation_id, operation_type, status, requested_by, input_json, progress_current, progress_total, created_at)
               VALUES (?, ?, 'queued', ?, ?, 0, ?, ?)""",
            (
                operation_id,
                operation_type,
                requested_by,
                input_json,
                progress_total,
                now,
            ),
        )
    return operation_id


def get_operation_job(conn: sqlite3.Connection, operation_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT operation_id, operation_type, status, requested_by, input_json, progress_current, progress_total, result_json, error_summary, created_at, started_at, finished_at FROM operation_jobs WHERE operation_id = ?",
        (operation_id,),
    )
    r = cursor.fetchone()
    if not r:
        return None
    return {
        "operation_id": r[0],
        "operation_type": r[1],
        "status": r[2],
        "requested_by": r[3],
        "input_json": r[4],
        "progress_current": r[5],
        "progress_total": r[6],
        "result_json": r[7],
        "error_summary": r[8],
        "created_at": r[9],
        "started_at": r[10],
        "finished_at": r[11],
    }


def update_operation_job(
    conn: sqlite3.Connection,
    operation_id: str,
    *,
    status: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
    result_json: str | None = None,
    error_summary: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
):
    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if progress_current is not None:
        updates.append("progress_current = ?")
        params.append(progress_current)
    if progress_total is not None:
        updates.append("progress_total = ?")
        params.append(progress_total)
    if result_json is not None:
        updates.append("result_json = ?")
        params.append(result_json)
    if error_summary is not None:
        updates.append("error_summary = ?")
        params.append(error_summary)
    if started_at is not None:
        updates.append("started_at = ?")
        params.append(started_at)
    if finished_at is not None:
        updates.append("finished_at = ?")
        params.append(finished_at)

    if not updates:
        return

    query = f"UPDATE operation_jobs SET {', '.join(updates)} WHERE operation_id = ?"
    params.append(operation_id)
    with transaction(conn):
        conn.execute(query, tuple(params))


def list_operation_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT operation_id, operation_type, status, requested_by, input_json, progress_current, progress_total, result_json, error_summary, created_at, started_at, finished_at FROM operation_jobs ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = []
    while True:
        batch = cursor.fetchmany(1000)
        if not batch:
            break
        rows.extend(batch)
    return [
        {
            "operation_id": r[0],
            "operation_type": r[1],
            "status": r[2],
            "requested_by": r[3],
            "input_json": r[4],
            "progress_current": r[5],
            "progress_total": r[6],
            "result_json": r[7],
            "error_summary": r[8],
            "created_at": r[9],
            "started_at": r[10],
            "finished_at": r[11],
        }
        for r in rows
    ]


# --- EXPORT PACKAGES ---

def create_export_package(
    conn: sqlite3.Connection,
    *,
    export_type: str,
    relative_path: str,
    sha256: str,
    byte_size: int,
    record_count: int | None,
    filters_json: str,
    created_by: str,
    expires_at: str | None = None,
    status: str = "building",
    export_id: str | None = None,
) -> str:
    if not export_id:
        export_id = f"exp-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO export_packages (export_id, export_type, relative_path, sha256, byte_size, record_count, filters_json, created_by, created_at, expires_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                export_id,
                export_type,
                relative_path,
                sha256,
                byte_size,
                record_count,
                filters_json,
                created_by,
                now,
                expires_at,
                status,
            ),
        )
    return export_id


def get_export_package(conn: sqlite3.Connection, export_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT export_id, export_type, relative_path, sha256, byte_size, record_count, filters_json, created_by, created_at, expires_at, status FROM export_packages WHERE export_id = ?",
        (export_id,),
    )
    r = cursor.fetchone()
    if not r:
        return None
    return {
        "export_id": r[0],
        "export_type": r[1],
        "relative_path": r[2],
        "sha256": r[3],
        "byte_size": r[4],
        "record_count": r[5],
        "filters_json": r[6],
        "created_by": r[7],
        "created_at": r[8],
        "expires_at": r[9],
        "status": r[10],
    }


def update_export_package_status(conn: sqlite3.Connection, export_id: str, status: str):
    with transaction(conn):
        conn.execute("UPDATE export_packages SET status = ? WHERE export_id = ?", (status, export_id))
