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
            "SELECT COALESCE(SUM(raw_bytes), 0) FROM harvest_items WHERE raw_bytes > 0 AND artifact_id IS NOT NULL AND status != 'duplicate'"
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


def get_harvest_dashboard_summary(db_path: Path | None = None) -> dict[str, Any]:
    if db_path is None:
        db_path = get_harvest_db_path()

    if not db_path.exists():
        return {
            "enabled": True,
            "initialized": False,
        }

    try:
        from mesa_legal_data.harvest.config import load_harvest_config
        from mesa_legal_data.harvest.discovery_state import get_discovery_cursor

        cfg = load_harvest_config()
        summary = get_harvest_status_summary(db_path=db_path)
        status_counts = summary.get("status_counts", {})

        conn = get_harvest_connection(db_path)
        last_run_status = None
        last_run_at = None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status, started_at FROM discovery_runs ORDER BY started_at DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                last_run_status = row["status"]
                last_run_at = row["started_at"]
        finally:
            conn.close()

        cursor_data = get_discovery_cursor("resmi_gazete", db_path=db_path) or {}

        target_bytes = cfg.target.raw_bytes or 32212254720
        raw_bytes = summary.get("total_raw_bytes", 0)
        progress_pct = round((raw_bytes / target_bytes) * 100, 2) if target_bytes > 0 else 0.0

        return {
            "enabled": cfg.enabled,
            "initialized": True,
            "total_items": summary.get("total_items", 0),
            "queued": status_counts.get("queued", 0),
            "needs_review": status_counts.get("needs_review", 0),
            "failed": status_counts.get("failed", 0),
            "retry_wait": status_counts.get("retry_wait", 0),
            "duplicate": status_counts.get("duplicate", 0),
            "raw_bytes": raw_bytes,
            "target_raw_bytes": target_bytes,
            "progress_percent": progress_pct,
            "source": "resmi_gazete",
            "last_discovery_status": last_run_status or "none",
            "last_discovery_at": last_run_at,
            "cursor_mode": cursor_data.get("mode", "backfill"),
            "cursor_date": cursor_data.get("last_successful_date") or cursor_data.get("next_date"),
        }
    except Exception:
        return {
            "enabled": True,
            "initialized": True,
            "status": "unavailable",
        }


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
