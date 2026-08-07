import shutil
from datetime import UTC, datetime
from pathlib import Path

from mesa_legal_data.config import load_settings
from mesa_legal_data.harvest.database import get_harvest_connection


def check_free_disk_space(
    minimum_free_bytes: int = 53687091200, custom_data_root: Path | None = None
) -> tuple[bool, int]:
    if custom_data_root is not None:
        data_root = custom_data_root
    else:
        settings = load_settings()
        data_root = settings.data_root_path

    data_root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(data_root)
    return usage.free >= minimum_free_bytes, usage.free


def get_total_raw_bytes(db_path: Path | None = None) -> int:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(raw_bytes), 0) FROM harvest_items WHERE status IN ('downloaded', 'processing', 'needs_review', 'completed')"
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()


def get_daily_budget_usage(
    source_id: str, budget_date: str | None = None, db_path: Path | None = None
) -> dict[str, int]:
    if budget_date is None:
        budget_date = datetime.now(UTC).strftime("%Y-%m-%d")

    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT requests_used, documents_downloaded, raw_bytes_downloaded, pipeline_success, pipeline_failed FROM daily_budgets WHERE source_id = ? AND budget_date = ?",
            (source_id, budget_date),
        )
        row = cursor.fetchone()
        if row:
            return {
                "requests_used": row["requests_used"],
                "documents_downloaded": row["documents_downloaded"],
                "raw_bytes_downloaded": row["raw_bytes_downloaded"],
                "pipeline_success": row["pipeline_success"],
                "pipeline_failed": row["pipeline_failed"],
            }
        return {
            "requests_used": 0,
            "documents_downloaded": 0,
            "raw_bytes_downloaded": 0,
            "pipeline_success": 0,
            "pipeline_failed": 0,
        }
    finally:
        conn.close()


def record_daily_budget(
    source_id: str,
    raw_bytes: int,
    success: bool,
    budget_date: str | None = None,
    db_path: Path | None = None,
) -> None:
    if budget_date is None:
        budget_date = datetime.now(UTC).strftime("%Y-%m-%d")

    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        succ_inc = 1 if success else 0
        fail_inc = 0 if success else 1
        doc_inc = 1 if success else 0

        cursor.execute(
            """
            INSERT INTO daily_budgets (source_id, budget_date, requests_used, documents_downloaded, raw_bytes_downloaded, pipeline_success, pipeline_failed)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(source_id, budget_date) DO UPDATE SET
                requests_used = requests_used + 1,
                documents_downloaded = documents_downloaded + ?,
                raw_bytes_downloaded = raw_bytes_downloaded + ?,
                pipeline_success = pipeline_success + ?,
                pipeline_failed = pipeline_failed + ?
            """,
            (
                source_id,
                budget_date,
                doc_inc,
                raw_bytes,
                succ_inc,
                fail_inc,
                doc_inc,
                raw_bytes,
                succ_inc,
                fail_inc,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def check_source_error_circuit_breaker(source_id: str, threshold: float = 0.25, db_path: Path | None = None) -> bool:
    """
    Returns True if error rate in last 100 finished items for this source exceeds threshold (circuit breaker triggered).
    """
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT status FROM harvest_items
            WHERE source_id = ? AND status IN ('completed', 'needs_review', 'failed', 'blocked')
            ORDER BY updated_at DESC LIMIT 100
            """,
            (source_id,),
        )
        rows = cursor.fetchall()
        if len(rows) < 10:
            return False

        fails = sum(1 for r in rows if r["status"] in ("failed", "blocked"))
        return (fails / len(rows)) >= threshold
    finally:
        conn.close()
