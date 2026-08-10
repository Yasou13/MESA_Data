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
            WHERE status IN ('queued', 'retry_wait', 'downloaded')
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


def _check_artifact_committed(artifact_id: str | None) -> bool:
    if not artifact_id:
        return False
    try:
        from mesa_legal_data.catalog import get_artifact, get_connection

        conn = get_connection()
        try:
            art = get_artifact(conn, artifact_id)
            return art is not None
        finally:
            conn.close()
    except Exception:
        return False


def _check_canonical_committed(
    artifact_id: str | None, db_path: Path | None = None
) -> tuple[bool, str | None, str | None]:
    if not artifact_id:
        return False, None, None

    # Check harvest.sqlite queue status first
    try:
        conn_h = get_harvest_connection(db_path)
        try:
            cursor = conn_h.cursor()
            cursor.execute(
                "SELECT status, version_id FROM harvest_items WHERE artifact_id = ? AND status IN ('completed', 'needs_review', 'duplicate')",
                (artifact_id,),
            )
            row = cursor.fetchone()
            if row:
                return True, row["status"], row["version_id"]
        finally:
            conn_h.close()
    except Exception:
        pass

    # Check catalog.sqlite
    try:
        from mesa_legal_data.catalog import get_artifact, get_connection, get_document, get_version

        conn = get_connection()
        try:
            art = get_artifact(conn, artifact_id)
            if art and art.get("document_id"):
                doc = get_document(conn, art["document_id"])
                if doc and doc.get("current_version_id"):
                    ver_id = doc["current_version_id"]
                    ver = get_version(conn, ver_id)
                    if ver:
                        v_app = ver.get("approval_status")
                        d_st = doc.get("lifecycle_status")

                        cursor = conn.cursor()
                        cursor.execute("SELECT approval_status FROM records WHERE version_id = ?", (ver_id,))
                        rec_rows = cursor.fetchall()
                        rec_statuses = set(r[0] for r in rec_rows) if rec_rows else set()

                        if v_app == "approved" or d_st == "approved":
                            if not any(s in ("pending", "needs_review", "rejected") for s in rec_statuses):
                                return True, "approved", ver_id

                        if (
                            "needs_review" in rec_statuses
                            or "pending" in rec_statuses
                            or v_app in ("needs_review", "pending")
                            or d_st in ("needs_review", "draft")
                        ):
                            return True, "needs_review", ver_id
                        elif "rejected" in rec_statuses or v_app == "rejected" or d_st == "rejected":
                            return True, "rejected", ver_id
                        elif rec_statuses and all(s == "approved" for s in rec_statuses):
                            return True, "approved", ver_id
                        elif not rec_statuses:
                            if v_app in ("approved", "needs_review", "rejected"):
                                return True, v_app, ver_id

                        return False, None, None
        finally:
            conn.close()
    except Exception:
        pass
    return False, None, None


def recover_expired_leases(db_path: Path | None = None) -> int:
    """
    Stage-aware crash recovery:
    - leased (expired): -> queued (or downloaded if raw artifact committed)
    - downloading (expired/stranded):
        committed artifact exists -> downloaded
        no committed artifact    -> queued
    - downloaded (expired/stranded): -> remain downloaded (unleased so runner processes it)
    - processing (expired/stranded):
        canonical result committed -> restore terminal/review state (completed / needs_review)
        no canonical result        -> downloaded (unleased so pipeline reruns)
    """
    conn = get_harvest_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    count = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM harvest_items
            WHERE status IN ('leased', 'downloading', 'downloaded', 'processing')
              AND (lease_expires_at IS NULL OR lease_expires_at < ?)
            """,
            (now_iso,),
        )
        rows = cursor.fetchall()
        for r in rows:
            item = row_to_harvest_item(r)
            st = item.status
            new_st = "queued"
            new_art_id = item.artifact_id
            new_ver_id = item.version_id

            if st == "leased":
                if item.artifact_id and _check_artifact_committed(item.artifact_id):
                    new_st = "downloaded"
                else:
                    new_st = "queued"
            elif st == "downloading":
                if item.artifact_id and _check_artifact_committed(item.artifact_id):
                    new_st = "downloaded"
                else:
                    new_st = "queued"
            elif st == "downloaded":
                new_st = "downloaded"
            elif st == "processing":
                has_canon, canon_st, ver_id = _check_canonical_committed(item.artifact_id, db_path=db_path)
                if has_canon:
                    if canon_st == "approved":
                        new_st = "completed"
                    elif canon_st in ("needs_review", "rejected", "pending"):
                        new_st = "needs_review"
                    else:
                        new_st = "downloaded"
                    new_ver_id = ver_id or item.version_id
                else:
                    new_st = "downloaded"

            status_changed = new_st != item.status
            lease_cleared = item.lease_owner is not None or item.lease_expires_at is not None

            cursor.execute(
                """
                UPDATE harvest_items
                SET status = ?,
                    artifact_id = ?,
                    version_id = ?,
                    lease_owner = NULL,
                    lease_started_at = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_st, new_art_id, new_ver_id, now_iso, item.id),
            )
            if status_changed or lease_cleared:
                count += 1
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

        # Timestamps management
        if t_status == ItemStatus.DOWNLOADED:
            if current_item.downloaded_at is None:
                updates.append("downloaded_at = ?")
                params.append(now_iso)
        if t_status in (ItemStatus.COMPLETED, ItemStatus.NEEDS_REVIEW):
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

        # Clear error state on successful/resumed statuses if no new error passed
        if t_status in (ItemStatus.DOWNLOADED, ItemStatus.PROCESSING, ItemStatus.COMPLETED, ItemStatus.NEEDS_REVIEW):
            if last_error_code is None:
                updates.append("last_error_code = NULL")
            if last_error_message is None:
                updates.append("last_error_message = NULL")
            if next_retry_at is None:
                updates.append("next_retry_at = NULL")

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


def operator_retry_item(item_id: int, db_path: Path | None = None) -> HarvestItem:
    """
    Operator action to retry a failed or retry_wait item.
    BLOCKED items cannot be retried automatically by operator.
    """
    item = get_harvest_item_by_id(item_id, db_path=db_path)
    if not item:
        raise ValueError(f"Harvest item {item_id} not found")
    if item.status == ItemStatus.BLOCKED.value:
        raise ValueError(f"Harvest item {item_id} is BLOCKED by security policy and cannot be retried by operator")

    conn = get_harvest_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE harvest_items
            SET status = 'queued',
                lease_owner = NULL,
                lease_started_at = NULL,
                lease_expires_at = NULL,
                next_retry_at = NULL,
                last_error_code = NULL,
                last_error_message = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now_iso, item_id),
        )
        conn.commit()
        cursor.execute("SELECT * FROM harvest_items WHERE id = ?", (item_id,))
        return row_to_harvest_item(cursor.fetchone())
    finally:
        conn.close()


def reconcile_harvest_review_status(
    version_id: str, db_path: Path | None = None, catalog_db_path: Path | None = None
) -> bool:
    """
    Reconciles a Harvest item's NEEDS_REVIEW status when human review for the associated version completes.
    """
    conn_h = get_harvest_connection(db_path)
    try:
        cursor_h = conn_h.cursor()
        cursor_h.execute(
            "SELECT id, status, artifact_id FROM harvest_items WHERE version_id = ? AND status = 'needs_review'",
            (version_id,),
        )
        row = cursor_h.fetchone()
        if not row:
            # Check by artifact_id if version_id match failed
            from mesa_legal_data.catalog import get_connection as get_cat_conn
            from mesa_legal_data.catalog import get_version

            cat_conn = get_cat_conn(catalog_db_path)
            try:
                ver = get_version(cat_conn, version_id)
                if ver and ver.get("artifact_id"):
                    cursor_h.execute(
                        "SELECT id, status, artifact_id FROM harvest_items WHERE artifact_id = ? AND status = 'needs_review'",
                        (ver["artifact_id"],),
                    )
                    row = cursor_h.fetchone()
            finally:
                cat_conn.close()
        if not row:
            return False

        item_id = row["id"]

        from mesa_legal_data.catalog import get_connection as get_cat_conn

        cat_conn = get_cat_conn(catalog_db_path)
        try:
            cursor_c = cat_conn.cursor()
            cursor_c.execute(
                "SELECT count(*) FROM records WHERE version_id = ? AND approval_status = 'pending'", (version_id,)
            )
            pending_count = cursor_c.fetchone()[0]
            if pending_count == 0:
                update_item_status(item_id, ItemStatus.COMPLETED, version_id=version_id, db_path=db_path)
                return True
        finally:
            cat_conn.close()
    except Exception:
        pass
    finally:
        conn_h.close()
    return False


def get_harvest_item_by_id(item_id: int, db_path: Path | None = None) -> HarvestItem | None:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM harvest_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return row_to_harvest_item(row) if row else None
    finally:
        conn.close()


def increment_item_attempts(item_id: int, db_path: Path | None = None) -> int:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE harvest_items SET attempts = attempts + 1 WHERE id = ?", (item_id,))
        conn.commit()
        cursor.execute("SELECT attempts FROM harvest_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        return row[0] if row else 1
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
        conn.commit()
    finally:
        conn.close()
