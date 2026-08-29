import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from mesa_legal_data.catalog import transaction
from mesa_legal_data.publisher.models import (
    DeliveryStatus,
    MesaTargetSettings,
)


def get_mesa_target_settings(conn: sqlite3.Connection, target_key: str = "default") -> MesaTargetSettings:
    """Fetches non-secret MESA target settings."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT target_key, base_url, tenant_id, workspace_id, dataset_id, agent_id, content_limit_chars, updated_at,
                  contract_source, health_path, publish_path, mutation_status_path_template
           FROM mesa_target_settings WHERE target_key = ?""",
        (target_key,),
    )
    row = cursor.fetchone()
    if row:
        return MesaTargetSettings(
            target_key=row[0],
            base_url=row[1],
            tenant_id=row[2],
            workspace_id=row[3],
            dataset_id=row[4],
            agent_id=row[5],
            content_limit_chars=row[6] or 32768,
            updated_at=row[7],
            contract_source=row[8],
            health_path=row[9],
            publish_path=row[10],
            mutation_status_path_template=row[11],
        )
    # Return sensible default
    return MesaTargetSettings(target_key=target_key)


def upsert_mesa_target_settings(conn: sqlite3.Connection, settings: MesaTargetSettings) -> None:
    """Upserts non-secret MESA target settings."""
    now_iso = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO mesa_target_settings (
                   target_key, base_url, tenant_id, workspace_id, dataset_id, agent_id,
                   content_limit_chars, updated_at, contract_source, health_path,
                   publish_path, mutation_status_path_template
               )
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(target_key) DO UPDATE SET
                   base_url = excluded.base_url,
                   tenant_id = excluded.tenant_id,
                   workspace_id = excluded.workspace_id,
                   dataset_id = excluded.dataset_id,
                   agent_id = excluded.agent_id,
                   content_limit_chars = excluded.content_limit_chars,
                   updated_at = excluded.updated_at,
                   contract_source = excluded.contract_source,
                   health_path = excluded.health_path,
                   publish_path = excluded.publish_path,
                   mutation_status_path_template = excluded.mutation_status_path_template""",
            (
                settings.target_key,
                settings.base_url,
                settings.tenant_id,
                settings.workspace_id,
                settings.dataset_id,
                settings.agent_id,
                settings.content_limit_chars,
                now_iso,
                settings.contract_source,
                settings.health_path,
                settings.publish_path,
                settings.mutation_status_path_template,
            ),
        )


def create_delivery(
    conn: sqlite3.Connection,
    *,
    delivery_id: str,
    release_id: str | None,
    target_key: str,
    total_items: int,
    target_config_sha256: str | None = None,
    release_manifest_sha256: str | None = None,
) -> None:
    now_iso = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO mesa_deliveries (
                   delivery_id, release_id, target_key, status, started_at, total_items,
                   committed_items, failed_items, skipped_items, created_at,
                   target_config_sha256, release_manifest_sha256
               ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)""",
            (
                delivery_id,
                release_id,
                target_key,
                DeliveryStatus.PLANNED.value,
                now_iso,
                total_items,
                now_iso,
                target_config_sha256,
                release_manifest_sha256,
            ),
        )


def update_delivery_progress(
    conn: sqlite3.Connection,
    *,
    delivery_id: str,
    status: str,
    committed_items: int,
    failed_items: int,
    skipped_items: int,
    last_error: str | None = None,
    finished: bool = False,
) -> None:
    now_iso = datetime.now(UTC).isoformat() if finished else None
    with transaction(conn):
        conn.execute(
            """UPDATE mesa_deliveries
               SET status = ?,
                   committed_items = ?,
                   failed_items = ?,
                   skipped_items = ?,
                   last_error = ?,
                   finished_at = COALESCE(?, finished_at)
               WHERE delivery_id = ?""",
            (status, committed_items, failed_items, skipped_items, last_error, now_iso, delivery_id),
        )


def insert_delivery_item(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    delivery_id: str,
    document_id: str,
    version_id: str,
    chunk_id: str,
    content_hash: str,
    idempotency_key: str,
    remote_state: str,
    payload_json: str,
) -> None:
    now_iso = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO mesa_delivery_items (item_id, delivery_id, document_id, version_id, chunk_id, content_hash, idempotency_key, remote_state, payload_json, updated_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                delivery_id,
                document_id,
                version_id,
                chunk_id,
                content_hash,
                idempotency_key,
                remote_state,
                payload_json,
                now_iso,
                now_iso,
            ),
        )


def update_delivery_item_state(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    remote_state: str,
    remote_mutation_id: str | None = None,
    last_error: str | None = None,
) -> None:
    now_iso = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """UPDATE mesa_delivery_items
               SET remote_state = ?,
                   remote_mutation_id = COALESCE(?, remote_mutation_id),
                   last_error = ?,
                   updated_at = ?
               WHERE item_id = ?""",
            (remote_state, remote_mutation_id, last_error, now_iso, item_id),
        )


def is_chunk_already_committed(
    conn: sqlite3.Connection,
    *,
    target_key: str,
    document_id: str,
    version_id: str,
    chunk_id: str,
    content_hash: str,
) -> bool:
    """
    Cross-release deduplication check:
    Returns True if an item with identical document, version, chunk, and content_hash
    was successfully COMMITTED to the target in any past delivery.
    """
    cursor = conn.cursor()
    cursor.execute(
        """SELECT 1 FROM mesa_delivery_items i
           JOIN mesa_deliveries d ON i.delivery_id = d.delivery_id
           WHERE d.target_key = ?
             AND i.document_id = ?
             AND i.version_id = ?
             AND i.chunk_id = ?
             AND i.content_hash = ?
             AND i.remote_state = 'COMMITTED'
           LIMIT 1""",
        (target_key, document_id, version_id, chunk_id, content_hash),
    )
    return cursor.fetchone() is not None


def list_deliveries(conn: sqlite3.Connection, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        """SELECT delivery_id, release_id, target_key, status, started_at, finished_at,
                  total_items, committed_items, failed_items, skipped_items, last_error, created_at,
                  target_config_sha256, release_manifest_sha256
           FROM mesa_deliveries ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    rows = cursor.fetchall()
    return [
        {
            "delivery_id": r[0],
            "release_id": r[1],
            "target_key": r[2],
            "status": r[3],
            "started_at": r[4],
            "finished_at": r[5],
            "total_items": r[6],
            "committed_items": r[7],
            "failed_items": r[8],
            "skipped_items": r[9],
            "last_error": r[10],
            "created_at": r[11],
            "target_config_sha256": r[12],
            "release_manifest_sha256": r[13],
        }
        for r in rows
    ]


def get_delivery(conn: sqlite3.Connection, delivery_id: str) -> dict[str, Any] | None:
    cursor = conn.cursor()
    cursor.execute(
        """SELECT delivery_id, release_id, target_key, status, started_at, finished_at,
                  total_items, committed_items, failed_items, skipped_items, last_error, created_at,
                  target_config_sha256, release_manifest_sha256
           FROM mesa_deliveries WHERE delivery_id = ?""",
        (delivery_id,),
    )
    r = cursor.fetchone()
    if not r:
        return None
    return {
        "delivery_id": r[0],
        "release_id": r[1],
        "target_key": r[2],
        "status": r[3],
        "started_at": r[4],
        "finished_at": r[5],
        "total_items": r[6],
        "committed_items": r[7],
        "failed_items": r[8],
        "skipped_items": r[9],
        "last_error": r[10],
        "created_at": r[11],
        "target_config_sha256": r[12],
        "release_manifest_sha256": r[13],
    }


def list_delivery_items(
    conn: sqlite3.Connection,
    delivery_id: str,
    state: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    if state:
        cursor.execute(
            """SELECT item_id, delivery_id, document_id, version_id, chunk_id, content_hash,
                      idempotency_key, remote_mutation_id, remote_state, payload_json, last_error, updated_at, created_at
               FROM mesa_delivery_items WHERE delivery_id = ? AND remote_state = ?
               ORDER BY created_at ASC LIMIT ? OFFSET ?""",
            (delivery_id, state, limit, offset),
        )
    else:
        cursor.execute(
            """SELECT item_id, delivery_id, document_id, version_id, chunk_id, content_hash,
                      idempotency_key, remote_mutation_id, remote_state, payload_json, last_error, updated_at, created_at
               FROM mesa_delivery_items WHERE delivery_id = ?
               ORDER BY created_at ASC LIMIT ? OFFSET ?""",
            (delivery_id, limit, offset),
        )
    rows = cursor.fetchall()
    results = []
    for r in rows:
        results.append(
            {
                "item_id": r[0],
                "delivery_id": r[1],
                "document_id": r[2],
                "version_id": r[3],
                "chunk_id": r[4],
                "content_hash": r[5],
                "idempotency_key": r[6],
                "remote_mutation_id": r[7],
                "remote_state": r[8],
                "payload": json.loads(r[9]) if r[9] else {},
                "last_error": r[10],
                "updated_at": r[11],
                "created_at": r[12],
            }
        )
    return results


def list_failed_delivery_items(conn: sqlite3.Connection, delivery_id: str) -> list[dict[str, Any]]:
    """Returns items eligible for retry in a delivery (FAILED or SENDING that timed out)."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT item_id, delivery_id, document_id, version_id, chunk_id, content_hash,
                  idempotency_key, remote_mutation_id, remote_state, payload_json, last_error, updated_at, created_at
           FROM mesa_delivery_items
           WHERE delivery_id = ? AND remote_state IN ('FAILED', 'SENDING', 'AWAITING_MUTATION')
           ORDER BY created_at ASC""",
        (delivery_id,),
    )
    rows = cursor.fetchall()
    return [
        {
            "item_id": r[0],
            "delivery_id": r[1],
            "document_id": r[2],
            "version_id": r[3],
            "chunk_id": r[4],
            "content_hash": r[5],
            "idempotency_key": r[6],
            "remote_mutation_id": r[7],
            "remote_state": r[8],
            "payload": json.loads(r[9]) if r[9] else {},
            "last_error": r[10],
            "updated_at": r[11],
            "created_at": r[12],
        }
        for r in rows
    ]


def get_document_mesa_status(conn: sqlite3.Connection, document_id: str) -> dict[str, Any]:
    """
    Computes truthful document-level MESA status:
      - 'Committed': All latest version chunks COMMITTED
      - 'Sending': Delivery in progress
      - 'Partial': Some chunks committed, some failed
      - 'Failed': Delivery failed
      - 'Not Sent': No delivery recorded
    """
    cursor = conn.cursor()
    cursor.execute(
        """WITH latest_items AS (
               SELECT i.remote_state,
                      ROW_NUMBER() OVER (
                          PARTITION BY i.chunk_id
                          ORDER BY i.updated_at DESC, i.created_at DESC
                      ) AS attempt_rank
               FROM mesa_delivery_items i
               JOIN documents d ON d.document_id = i.document_id
               WHERE i.document_id = ? AND i.version_id = d.current_version_id
           )
           SELECT remote_state, count(*)
           FROM latest_items
           WHERE attempt_rank = 1
           GROUP BY remote_state""",
        (document_id,),
    )
    counts = dict((r[0], r[1]) for r in cursor.fetchall())
    if not counts:
        cursor.execute("SELECT 1 FROM mesa_delivery_items WHERE document_id = ? LIMIT 1", (document_id,))
        status = "Update Pending" if cursor.fetchone() else "Not Sent"
        return {"status": status, "committed_count": 0, "failed_count": 0, "total_chunks": 0}

    total = sum(counts.values())
    committed = counts.get("COMMITTED", 0) + counts.get("SKIPPED", 0)
    failed = counts.get("FAILED", 0) + counts.get("REJECTED", 0)
    sending = (
        counts.get("SENDING", 0)
        + counts.get("QUEUED", 0)
        + counts.get("PROCESSING", 0)
        + counts.get("AWAITING_MUTATION", 0)
    )

    if sending > 0:
        status = "Sending"
    elif failed > 0 and committed > 0:
        status = "Partial"
    elif failed > 0 and committed == 0:
        status = "Failed"
    elif committed == total and total > 0:
        status = "Committed"
    else:
        status = "Update Pending"

    return {
        "status": status,
        "committed_count": committed,
        "failed_count": failed,
        "total_chunks": total,
        "counts_by_state": counts,
    }
