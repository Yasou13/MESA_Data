import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from mesa_legal_data.audit import log_audit_event, run_integrity_audit
from mesa_legal_data.catalog import (
    get_connection,
    get_operation_job,
    transaction,
    update_operation_job,
)
from mesa_legal_data.exports import generate_export_package
from mesa_legal_data.release.builder import build_release

_cancelled_jobs: set[str] = set()
_executor = ThreadPoolExecutor(max_workers=1)


def is_cancelled(operation_id: str) -> bool:
    return operation_id in _cancelled_jobs


def cancel_operation(conn: sqlite3.Connection, operation_id: str, actor: str = "operator"):
    _cancelled_jobs.add(operation_id)
    with transaction(conn):
        conn.execute(
            "UPDATE operation_jobs SET status = 'cancelled' WHERE operation_id = ?",
            (operation_id,),
        )
        log_audit_event(
            conn,
            actor=actor,
            action="operation_cancel",
            subject_type="operation",
            subject_id=operation_id,
        )


def recover_interrupted_operations(conn: sqlite3.Connection):
    """
    On server startup, moves any operations stuck in 'running' to 'interrupted'.
    """
    with transaction(conn):
        conn.execute(
            "UPDATE operation_jobs SET status = 'interrupted' WHERE status = 'running'",
        )


def submit_operation(
    conn: sqlite3.Connection,
    *,
    operation_type: str,
    requested_by: str,
    input_dict: dict[str, Any],
) -> str:
    op_id = f"op-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    with transaction(conn):
        conn.execute(
            """INSERT INTO operation_jobs (operation_id, operation_type, requested_by, status, input_json, progress_current, progress_total, result_json, error_summary, created_at)
               VALUES (?, ?, ?, 'queued', ?, 0, 100, '{}', NULL, ?)""",
            (op_id, operation_type, requested_by, json.dumps(input_dict), now),
        )
        log_audit_event(
            conn,
            actor=requested_by,
            action="operation_submit",
            subject_type="operation",
            subject_id=op_id,
            details_json=json.dumps({"operation_type": operation_type}),
        )

    _executor.submit(_run_operation_task, op_id)
    return op_id


def run_operation_sync(conn: sqlite3.Connection, operation_id: str):
    _run_operation_task(operation_id)


def _run_operation_task(operation_id: str):
    conn = get_connection()
    job = get_operation_job(conn, operation_id)
    if not job or job["status"] in ("cancelled", "interrupted"):
        conn.close()
        return

    update_operation_job(conn, operation_id, status="running", progress_current=10)

    try:
        if is_cancelled(operation_id):
            update_operation_job(conn, operation_id, status="cancelled")
            conn.close()
            return

        op_type = job["operation_type"]
        inp = json.loads(job["input_json"]) if job.get("input_json") else {}

        if op_type == "filtered_export":
            export_id = f"exp-{uuid.uuid4().hex[:12]}"
            res = generate_export_package(
                conn,
                export_id=export_id,
                export_type=inp.get("export_type", "records_jsonl"),
                filters=inp.get("filters", {}),
                actor=job.get("requested_by", "operator"),
            )
            update_operation_job(
                conn,
                operation_id,
                status="succeeded",
                progress_current=100,
                result_json=json.dumps(res),
            )
        elif op_type == "release_build":
            rel_id = inp.get("release_id") or f"rel-{uuid.uuid4().hex[:8]}"
            res = build_release(release_id=rel_id)
            update_operation_job(
                conn,
                operation_id,
                status="succeeded",
                progress_current=100,
                result_json=json.dumps(res),
            )
        elif op_type == "integrity_audit":
            res = run_integrity_audit()
            update_operation_job(
                conn,
                operation_id,
                status="succeeded",
                progress_current=100,
                result_json=json.dumps(res),
            )
        else:
            update_operation_job(
                conn,
                operation_id,
                status="succeeded",
                progress_current=100,
                result_json=json.dumps({"operation_id": operation_id, "processed": True}),
            )
    except Exception as exc:
        update_operation_job(
            conn,
            operation_id,
            status="failed",
            error_summary=str(exc),
        )
    finally:
        conn.close()
