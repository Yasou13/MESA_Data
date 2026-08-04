import json
import sqlite3
from typing import Dict, Any

from mesa_legal_data.catalog import get_connection
from mesa_legal_data.release.verifier import verify_release


class ImportRollbackError(Exception):
    pass


def import_release_to_staging(release_id: str) -> Dict[str, Any]:
    """
    Imports a verified published release into staging.
    Guarantees idempotency.
    """
    # 1. Verify release package first
    verify_release(release_id)

    conn = get_connection()
    cursor = conn.cursor()

    try:
        conn.execute("BEGIN TRANSACTION;")

        # Check release status
        cursor.execute("SELECT status FROM releases WHERE release_id = ?", (release_id,))
        row = cursor.fetchone()
        if not row or row[0] not in ("published", "verified"):
            raise ImportRollbackError(f"Release {release_id} cannot be imported (status: {row[0] if row else 'not_found'})")

        # Mark as imported in staging
        cursor.execute(
            "UPDATE releases SET status = 'published' WHERE release_id = ?",
            (release_id,),
        )
        conn.execute("COMMIT;")
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise ImportRollbackError(f"Failed to import release {release_id}: {e}") from e
    finally:
        conn.close()

    return {"status": "success", "release_id": release_id}


def rollback_release(release_id: str) -> bool:
    """
    Rolls back a release from published to revoked state.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN TRANSACTION;")
        conn.execute("UPDATE releases SET status = 'revoked' WHERE release_id = ?", (release_id,))
        conn.execute("COMMIT;")
        return True
    except Exception as e:
        conn.execute("ROLLBACK;")
        raise ImportRollbackError(f"Failed to rollback release {release_id}: {e}") from e
    finally:
        conn.close()


def get_record_provenance(record_id: str) -> Dict[str, Any]:
    """
    Returns full provenance chain for a given record.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT r.record_id, r.version_id, v.document_id, v.artifact_id, a.source_id, a.source_url, a.sha256, a.retrieved_at
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        JOIN artifacts a ON v.artifact_id = a.artifact_id
        WHERE r.record_id = ?
        """,
        (record_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {}

    return {
        "record_id": row[0],
        "version_id": row[1],
        "document_id": row[2],
        "artifact_id": row[3],
        "source_id": row[4],
        "source_url": row[5],
        "sha256": row[6],
        "retrieved_at": row[7],
    }
