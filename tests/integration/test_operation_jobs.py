import time
import pytest

from mesa_legal_data.catalog import (
    create_operation_job,
    get_connection,
    get_db_path,
    get_operation_job,
    migrate,
)
from mesa_legal_data.operations import (
    cancel_operation,
    recover_interrupted_operations,
    run_operation_sync,
    submit_operation,
)


def test_operation_jobs_lifecycle_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    conn = get_connection()

    # 1. Submit operation job
    op_id = submit_operation(
        conn,
        operation_type="integrity_audit",
        requested_by="test_op_user",
        input_dict={},
    )
    assert op_id.startswith("op-")

    job_initial = get_operation_job(conn, op_id)
    assert job_initial["status"] in ("queued", "running", "succeeded")

    # Sync run to ensure completion in test
    run_operation_sync(conn, op_id)

    job_final = get_operation_job(conn, op_id)
    assert job_final["status"] == "succeeded"
    assert job_final["progress_current"] == 100

    # 2. Cancel operation job
    op_cancel_id = submit_operation(
        conn,
        operation_type="bulk_review",
        requested_by="test_op_user",
        input_dict={},
    )
    cancel_operation(conn, op_cancel_id, actor="test_canceller")
    job_canceled = get_operation_job(conn, op_cancel_id)
    assert job_canceled["status"] == "cancelled"

    # 3. Server recovery test: running -> interrupted
    c = conn.cursor()
    c.execute(
        """INSERT INTO operation_jobs (operation_id, operation_type, requested_by, status, input_json, progress_current, progress_total, result_json, error_summary, created_at)
           VALUES ('op-stuck-1', 'bulk_review', 'tester', 'running', '{}', 50, 100, '{}', NULL, '2026-08-05T00:00:00Z')"""
    )
    conn.commit()

    recover_interrupted_operations(conn)

    job_interrupted = get_operation_job(conn, "op-stuck-1")
    assert job_interrupted["status"] == "interrupted"

    conn.close()
