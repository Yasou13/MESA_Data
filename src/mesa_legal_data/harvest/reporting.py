from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.harvest.database import get_harvest_connection, get_harvest_db_path


def get_harvest_status_summary(db_path: Path | None = None) -> dict[str, Any]:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()

        # Status counts
        cursor.execute("SELECT status, COUNT(*) as cnt FROM harvest_items GROUP BY status")
        status_counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}

        # Total raw bytes
        cursor.execute(
            "SELECT COALESCE(SUM(raw_bytes), 0) FROM harvest_items WHERE status IN ('downloaded', 'processing', 'needs_review', 'completed')"
        )
        total_raw_bytes = cursor.fetchone()[0]

        # Total items
        cursor.execute("SELECT COUNT(*) FROM harvest_items")
        total_items = cursor.fetchone()[0]

        return {
            "total_items": total_items,
            "status_counts": status_counts,
            "total_raw_bytes": total_raw_bytes,
        }
    finally:
        conn.close()


def get_harvest_failures(limit: int = 50, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, queue_id, source_id, canonical_key, normalized_url, status, attempts,
                   last_error_code, last_error_message, next_retry_at, updated_at
            FROM harvest_items
            WHERE status IN ('failed', 'blocked', 'retry_wait')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def backup_harvest_db(backup_dir: Path | None = None, db_path: Path | None = None) -> Path:
    if db_path is None:
        db_path = get_harvest_db_path()

    if not db_path.exists():
        raise FileNotFoundError(f"Harvest database not found at {db_path}")

    if backup_dir is None:
        backup_dir = db_path.parent / "backups"

    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target_path = backup_dir / f"harvest_backup_{ts}.sqlite"

    conn = get_harvest_connection(db_path)
    b_conn = get_harvest_connection(target_path)
    try:
        conn.backup(b_conn)
    finally:
        b_conn.close()
        conn.close()

    return target_path
