import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.harvest.database import get_harvest_connection


def get_discovery_cursor(source_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT cursor_data_json FROM discovery_cursors WHERE source_id = ?", (source_id,))
        row = cursor.fetchone()
        if row and row["cursor_data_json"]:
            return json.loads(row["cursor_data_json"])
        return None
    finally:
        conn.close()


def save_discovery_cursor(source_id: str, data: dict[str, Any], db_path: Path | None = None) -> None:
    conn = get_harvest_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO discovery_cursors (source_id, cursor_data_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                cursor_data_json = excluded.cursor_data_json,
                updated_at = excluded.updated_at
            """,
            (source_id, json.dumps(data), now_iso),
        )
        conn.commit()
    finally:
        conn.close()


def start_discovery_run(source_id: str, db_path: Path | None = None) -> str:
    conn = get_harvest_connection(db_path)
    run_id = f"disc-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(UTC).isoformat()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE discovery_runs SET status = 'interrupted', finished_at = ? WHERE source_id = ? AND status = 'running'",
            (now_iso, source_id),
        )
        cursor.execute(
            """
            INSERT INTO discovery_runs (
                run_id, source_id, started_at, status,
                pages_visited, links_seen, items_inserted, items_duplicate, items_skipped
            ) VALUES (?, ?, ?, 'running', 0, 0, 0, 0, 0)
            """,
            (run_id, source_id, now_iso),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def finish_discovery_run(
    run_id: str,
    status: str,
    pages_visited: int,
    links_seen: int,
    items_inserted: int,
    items_duplicate: int,
    items_skipped: int,
    error_message: str | None = None,
    db_path: Path | None = None,
) -> None:
    conn = get_harvest_connection(db_path)
    now_iso = datetime.now(UTC).isoformat()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE discovery_runs SET
                finished_at = ?,
                status = ?,
                pages_visited = ?,
                links_seen = ?,
                items_inserted = ?,
                items_duplicate = ?,
                items_skipped = ?,
                error_message = ?
            WHERE run_id = ?
            """,
            (
                now_iso,
                status,
                pages_visited,
                links_seen,
                items_inserted,
                items_duplicate,
                items_skipped,
                error_message,
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
