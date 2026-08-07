import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mesa_legal_data.harvest.database import get_harvest_connection
from mesa_legal_data.harvest.models import (
    DiscoveredDocument,
    HarvestItem,
    ItemStatus,
    SelectionDecision,
    validate_status_transition,
)
from mesa_legal_data.harvest.normalization import normalize_url


def row_to_harvest_item(row: sqlite3.Row) -> HarvestItem:
    return HarvestItem(
        id=row["id"],
        queue_id=row["queue_id"],
        source_id=row["source_id"],
        adapter_name=row["adapter_name"],
        canonical_key=row["canonical_key"],
        normalized_url=row["normalized_url"],
        original_url=row["original_url"],
        document_id=row["document_id"],
        family=row["family"],
        document_type=row["document_type"],
        title=row["title"],
        publication_date=row["publication_date"],
        discovery_page_url=row["discovery_page_url"],
        selection_reasons_json=row["selection_reasons_json"],
        priority=row["priority"],
        status=row["status"],
        attempts=row["attempts"],
        next_retry_at=row["next_retry_at"],
        lease_owner=row["lease_owner"],
        lease_started_at=row["lease_started_at"],
        lease_expires_at=row["lease_expires_at"],
        artifact_id=row["artifact_id"],
        version_id=row["version_id"],
        raw_bytes=row["raw_bytes"],
        detected_content_type=row["detected_content_type"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        discovered_at=row["discovered_at"],
        downloaded_at=row["downloaded_at"],
        pipeline_completed_at=row["pipeline_completed_at"],
        completed_at=row["completed_at"],
        updated_at=row["updated_at"],
    )


def enqueue_discovered_document(
    doc: DiscoveredDocument,
    adapter_name: str,
    decision: SelectionDecision,
    db_path: Path | None = None,
) -> tuple[HarvestItem | None, str]:
    """
    Enqueues a discovered document into harvest.sqlite.
    Returns (HarvestItem, 'inserted' | 'duplicate' | 'skipped').
    """
    norm_url = normalize_url(doc.document_url)
    now_iso = datetime.now(UTC).isoformat()
    pub_date_str = doc.publication_date.isoformat() if doc.publication_date else None

    status = ItemStatus.QUEUED.value if decision.accepted else ItemStatus.SKIPPED.value
    queue_id = f"hq-{uuid.uuid4().hex[:12]}"
    reasons_json = json.dumps(list(decision.reasons))

    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO harvest_items (
                queue_id, source_id, adapter_name, canonical_key, normalized_url, original_url,
                document_id, family, document_type, title, publication_date, discovery_page_url,
                selection_reasons_json, priority, status, discovered_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                queue_id,
                doc.source_id,
                adapter_name,
                doc.canonical_key,
                norm_url,
                doc.document_url,
                doc.document_id,
                doc.family,
                doc.document_type,
                doc.title,
                pub_date_str,
                doc.discovery_page_url,
                reasons_json,
                decision.priority,
                status,
                now_iso,
                now_iso,
            ),
        )
        item_id = cursor.lastrowid
        conn.commit()

        cursor.execute("SELECT * FROM harvest_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        item = row_to_harvest_item(row)
        return item, "inserted" if decision.accepted else "skipped"

    except sqlite3.IntegrityError:
        conn.rollback()
        # Item already exists in queue by canonical_key or normalized_url
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM harvest_items WHERE source_id = ? AND (canonical_key = ? OR normalized_url = ?)",
            (doc.source_id, doc.canonical_key, norm_url),
        )
        row = cursor.fetchone()
        dup_item = row_to_harvest_item(row) if row else None
        return dup_item, "duplicate"
    finally:
        conn.close()


def acquire_lease_batch(
    worker_id: str,
    batch_size: int = 25,
    lease_seconds: int = 1800,
    db_path: Path | None = None,
) -> list[HarvestItem]:
    """
    Atomically leases up to batch_size items using BEGIN IMMEDIATE.
    """
    conn = get_harvest_connection(db_path)
    leased_items: list[HarvestItem] = []
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    expires_iso = (now + timedelta(seconds=lease_seconds)).isoformat()

    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM harvest_items
            WHERE status IN ('queued', 'retry_wait')
              AND (next_retry_at IS NULL OR next_retry_at <= ?)
              AND (lease_expires_at IS NULL OR lease_expires_at < ?)
            ORDER BY priority DESC, discovered_at ASC
            LIMIT ?
            """,
            (now_iso, now_iso, batch_size),
        )
        rows = cursor.fetchall()
        if not rows:
            conn.commit()
            return []

        item_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in item_ids)

        cursor.execute(
            f"""
            UPDATE harvest_items
            SET status = 'leased',
                lease_owner = ?,
                lease_started_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [worker_id, now_iso, expires_iso, now_iso] + item_ids,
        )
        conn.commit()

        cursor.execute(f"SELECT * FROM harvest_items WHERE id IN ({placeholders})", item_ids)
        leased_items = [row_to_harvest_item(r) for r in cursor.fetchall()]
        return leased_items
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def recover_expired_leases(db_path: Path | None = None) -> int:
    """
    Reclaims leased items whose lease has expired back to 'queued'.
    """
    conn = get_harvest_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE harvest_items
            SET status = 'queued',
                lease_owner = NULL,
                lease_started_at = NULL,
                lease_expires_at = NULL,
                updated_at = ?
            WHERE status = 'leased' AND lease_expires_at < ?
            """,
            (now_iso, now_iso),
        )
        count = cursor.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def update_item_status(
    item_id: int,
    target_status: ItemStatus | str,
    *,
    artifact_id: str | None = None,
    version_id: str | None = None,
    raw_bytes: int | None = None,
    detected_content_type: str | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    next_retry_at: str | None = None,
    db_path: Path | None = None,
) -> HarvestItem:
    conn = get_harvest_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    t_status = ItemStatus(target_status)

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM harvest_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Harvest item {item_id} not found")

        current_item = row_to_harvest_item(row)
        validate_status_transition(current_item.status, t_status)

        updates = ["status = ?", "updated_at = ?"]
        params: list[Any] = [t_status.value, now_iso]

        if artifact_id is not None:
            updates.append("artifact_id = ?")
            params.append(artifact_id)
        if version_id is not None:
            updates.append("version_id = ?")
            params.append(version_id)
        if raw_bytes is not None:
            updates.append("raw_bytes = ?")
            params.append(raw_bytes)
        if detected_content_type is not None:
            updates.append("detected_content_type = ?")
            params.append(detected_content_type)
        if last_error_code is not None:
            updates.append("last_error_code = ?")
            params.append(last_error_code)
        if last_error_message is not None:
            updates.append("last_error_message = ?")
            params.append(last_error_message)
        if next_retry_at is not None:
            updates.append("next_retry_at = ?")
            params.append(next_retry_at)

        if t_status == ItemStatus.DOWNLOADED or t_status == ItemStatus.COMPLETED:
            updates.append("downloaded_at = ?")
            params.append(now_iso)
        if t_status == ItemStatus.COMPLETED or t_status == ItemStatus.NEEDS_REVIEW:
            updates.append("pipeline_completed_at = ?")
            params.append(now_iso)
        if t_status in (
            ItemStatus.COMPLETED,
            ItemStatus.DUPLICATE,
            ItemStatus.BLOCKED,
            ItemStatus.FAILED,
            ItemStatus.SKIPPED,
        ):
            updates.append("completed_at = ?")
            params.append(now_iso)

        # Clear lease on terminal/retry/queued status
        if t_status in (
            ItemStatus.QUEUED,
            ItemStatus.RETRY_WAIT,
            ItemStatus.COMPLETED,
            ItemStatus.NEEDS_REVIEW,
            ItemStatus.FAILED,
            ItemStatus.BLOCKED,
            ItemStatus.DUPLICATE,
            ItemStatus.SKIPPED,
        ):
            updates.append("lease_owner = NULL")
            updates.append("lease_started_at = NULL")
            updates.append("lease_expires_at = NULL")

        sql = f"UPDATE harvest_items SET {', '.join(updates)} WHERE id = ?"
        params.append(item_id)

        cursor.execute(sql, params)
        conn.commit()

        cursor.execute("SELECT * FROM harvest_items WHERE id = ?", (item_id,))
        return row_to_harvest_item(cursor.fetchone())
    finally:
        conn.close()


def record_attempt(
    item_id: int,
    attempt_number: int,
    stage: str,
    started_at: str,
    finished_at: str,
    result: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    http_status: int | None = None,
    bytes_received: int = 0,
    artifact_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO harvest_attempts (
                item_id, attempt_number, stage, started_at, finished_at, result,
                error_code, error_message, http_status, bytes_received, artifact_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                attempt_number,
                stage,
                started_at,
                finished_at,
                result,
                error_code,
                error_message,
                http_status,
                bytes_received,
                artifact_id,
            ),
        )
        cursor.execute("UPDATE harvest_items SET attempts = attempts + 1 WHERE id = ?", (item_id,))
        conn.commit()
    finally:
        conn.close()
