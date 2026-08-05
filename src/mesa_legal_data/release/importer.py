import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.catalog import (
    get_connection as get_catalog_connection,
)
from mesa_legal_data.catalog import (
    record_mesa_import,
)
from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.release.verifier import verify_release
from mesa_legal_data.schema_validation import validate_record


class ReleaseNotFound(Exception):
    pass


class ReleaseNotPublished(Exception):
    pass


class ReleaseRevoked(Exception):
    pass


class ReleaseStateChanged(Exception):
    pass


class ImportRollbackError(Exception):
    pass


def get_staging_db_path() -> Path:
    settings = load_settings()
    if settings.mesa_staging_db and not settings.mesa_staging_db.startswith("/storage/"):
        p = Path(settings.mesa_staging_db).expanduser().resolve()
    else:
        p = settings.data_root_path / "mesa_staging.sqlite"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = settings.data_root_path / "mesa_staging.sqlite"
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_staging_connection(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = get_staging_db_path()

    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def init_staging_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS imported_releases (
            release_id TEXT PRIMARY KEY,
            manifest_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS staging_records (
            release_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            record_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (release_id, record_id),
            FOREIGN KEY (release_id) REFERENCES imported_releases(release_id)
        );

        CREATE TABLE IF NOT EXISTS active_release (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            release_id TEXT,
            activated_at TEXT
        );
    """)


def import_release_to_staging(release_id: str, batch_size: int = 2000) -> dict[str, Any]:
    """
    Imports a published, verified release package into the MESA staging database.
    Enforces catalog 'published' status check, streaming JSONL reading, and atomic rollback.
    """
    # 0. Check catalog database status first
    cat_conn = get_catalog_connection()
    c = cat_conn.cursor()
    c.execute("SELECT release_id, status FROM releases WHERE release_id = ?", (release_id,))
    row = c.fetchone()
    cat_conn.close()

    if not row:
        raise ReleaseNotFound(f"RELEASE_NOT_FOUND: Release '{release_id}' not found in catalog")

    _, cat_status = row
    if cat_status == "revoked":
        raise ReleaseRevoked(f"RELEASE_REVOKED: Release '{release_id}' has been revoked")

    if cat_status != "published":
        raise ReleaseNotPublished(
            f"RELEASE_NOT_PUBLISHED: Release '{release_id}' is in status '{cat_status}', must be 'published'"
        )

    # 1. Verify release package integrity on disk
    verify_release(release_id)

    settings = load_settings()
    data_root = settings.data_root_path
    release_dir = data_root / "releases" / release_id
    manifest_path = release_dir / "manifest.json"

    with open(manifest_path, "rb") as f:
        manifest_sha256 = hash_stream(f)

    stg_conn = get_staging_connection()
    init_staging_db(stg_conn)

    cursor = stg_conn.cursor()

    # Check if already imported
    cursor.execute(
        "SELECT manifest_sha256, status FROM imported_releases WHERE release_id = ?",
        (release_id,),
    )
    existing = cursor.fetchone()
    if existing:
        stored_manifest, _stored_status = existing
        if stored_manifest == manifest_sha256:
            stg_conn.close()
            return {
                "status": "already_imported",
                "release_id": release_id,
                "message": "Release already imported with identical manifest SHA-256",
            }
        else:
            stg_conn.close()
            raise ImportRollbackError(
                f"Release {release_id} already imported with different manifest SHA-256 collision"
            )

    # 2. Stream JSONL records in batches
    data_dir = release_dir / "data"
    jsonl_files = sorted(list(data_dir.glob("*.jsonl")))

    type_counts = {"legislation": 0, "article": 0, "decision": 0, "citation": 0}
    now_iso = datetime.now(UTC).isoformat()
    records_batch: list[tuple[str, str, str, str, str]] = []

    try:
        stg_conn.execute("BEGIN TRANSACTION;")

        stg_conn.execute(
            "INSERT INTO imported_releases (release_id, manifest_sha256, imported_at, status) VALUES (?, ?, ?, 'importing')",
            (release_id, manifest_sha256, now_iso),
        )

        for jf in jsonl_files:
            with open(jf, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f, start=1):
                    line_str = line.strip()
                    if not line_str:
                        continue

                    rec_obj = json.loads(line_str)
                    validate_record(rec_obj)

                    r_id = rec_obj["id"]
                    r_type = rec_obj["record_type"]
                    rec_sha = hashlib.sha256(line.encode("utf-8")).hexdigest()

                    if r_type in type_counts:
                        type_counts[r_type] += 1

                    records_batch.append((release_id, r_id, r_type, rec_sha, json_str_deterministic(rec_obj)))

                    if len(records_batch) >= batch_size:
                        stg_conn.executemany(
                            "INSERT INTO staging_records (release_id, record_id, record_type, record_sha256, payload_json) VALUES (?, ?, ?, ?, ?)",
                            records_batch,
                        )
                        records_batch.clear()

        if records_batch:
            stg_conn.executemany(
                "INSERT INTO staging_records (release_id, record_id, record_type, record_sha256, payload_json) VALUES (?, ?, ?, ?, ?)",
                records_batch,
            )
            records_batch.clear()

        # Re-check catalog status before committing & updating active pointer
        cat_conn = get_catalog_connection()
        c = cat_conn.cursor()
        c.execute("SELECT status FROM releases WHERE release_id = ?", (release_id,))
        latest_row = c.fetchone()
        cat_conn.close()

        if not latest_row or latest_row[0] != "published":
            latest_status = latest_row[0] if latest_row else "missing"
            raise ReleaseStateChanged(
                f"RELEASE_STATE_CHANGED: Release '{release_id}' status is '{latest_status}', expected 'published'"
            )

        stg_conn.execute(
            "UPDATE imported_releases SET status = 'imported' WHERE release_id = ?",
            (release_id,),
        )

        stg_conn.execute(
            "INSERT OR REPLACE INTO active_release (singleton_id, release_id, activated_at) VALUES (1, ?, ?)",
            (release_id, now_iso),
        )

        stg_conn.execute("COMMIT;")
    except Exception as e:
        stg_conn.execute("ROLLBACK;")
        stg_conn.close()

        if isinstance(e, (ReleaseNotFound, ReleaseNotPublished, ReleaseRevoked, ReleaseStateChanged)):
            raise e
        raise ImportRollbackError(f"Failed staging import for release {release_id}: {e}") from e

    stg_conn.close()

    # Audit in catalog DB
    cat_conn = get_catalog_connection()
    record_mesa_import(
        conn=cat_conn,
        release_id=release_id,
        status="imported",
        target_db_path=str(settings.mesa_staging_db),
        imported_at=now_iso,
        record_counts_json=json.dumps(type_counts),
        error_summary=None,
    )
    cat_conn.close()

    return {
        "status": "imported",
        "release_id": release_id,
        "counts": type_counts,
    }


def json_str_deterministic(rec: dict[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rollback_release(target_release_id: str) -> dict[str, Any]:
    """
    Rolls back active release in MESA staging to a previously imported target_release_id.
    """
    stg_conn = get_staging_connection()
    init_staging_db(stg_conn)
    cursor = stg_conn.cursor()

    cursor.execute(
        "SELECT release_id FROM imported_releases WHERE release_id = ?",
        (target_release_id,),
    )
    if not cursor.fetchone():
        stg_conn.close()
        raise ImportRollbackError(f"Target release {target_release_id} has not been imported into staging DB")

    now_iso = datetime.now(UTC).isoformat()
    try:
        stg_conn.execute("BEGIN TRANSACTION;")
        stg_conn.execute(
            "INSERT OR REPLACE INTO active_release (singleton_id, release_id, activated_at) VALUES (1, ?, ?)",
            (target_release_id, now_iso),
        )
        stg_conn.execute("COMMIT;")
    except Exception as e:
        stg_conn.execute("ROLLBACK;")
        stg_conn.close()
        raise ImportRollbackError(f"Failed to rollback active release to {target_release_id}: {e}") from e

    stg_conn.close()

    cat_conn = get_catalog_connection()
    record_mesa_import(
        conn=cat_conn,
        release_id=target_release_id,
        status="imported",
        target_db_path=str(load_settings().mesa_staging_db),
        imported_at=now_iso,
        record_counts_json="{}",
        error_summary=f"Active release set via rollback to {target_release_id}",
    )
    cat_conn.close()

    return {"status": "rolled_back", "active_release_id": target_release_id}


def get_record_provenance(record_id: str) -> dict[str, Any]:
    """
    Returns full provenance chain for a given record.
    """
    cat_conn = get_catalog_connection()
    cursor = cat_conn.cursor()

    cursor.execute(
        """
        SELECT r.record_id, r.version_id, r.canonical_path, r.canonical_line, r.record_sha256,
               v.document_id, v.artifact_id, a.source_id, a.source_url, a.sha256, a.retrieved_at
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        JOIN artifacts a ON v.artifact_id = a.artifact_id
        WHERE r.record_id = ?
        """,
        (record_id,),
    )
    row = cursor.fetchone()

    stg_conn = get_staging_connection()
    init_staging_db(stg_conn)
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    active_row = stg_cur.fetchone()
    active_release_id = active_row[0] if active_row else None
    stg_conn.close()
    cat_conn.close()

    if not row:
        return {}

    return {
        "active_release_id": active_release_id,
        "record_id": row[0],
        "version_id": row[1],
        "canonical_path": row[2],
        "canonical_line": row[3],
        "record_sha256": row[4],
        "document_id": row[5],
        "artifact_id": row[6],
        "source_id": row[7],
        "source_url": row[8],
        "raw_sha256": row[9],
        "retrieved_at": row[10],
    }
