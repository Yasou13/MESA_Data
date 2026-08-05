import csv
import hashlib
import json
import sqlite3
import tarfile
from pathlib import Path
from typing import Any

from mesa_legal_data.catalog import create_export_package, get_record
from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.release.importer import get_record_provenance


def generate_export_package(
    conn: sqlite3.Connection,
    *,
    export_id: str,
    export_type: str,
    filters: dict[str, Any] | None = None,
    actor: str,
) -> dict[str, Any]:
    if filters is None:
        filters = {}
    data_root = load_settings().data_root_path
    exports_dir = data_root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    if export_type == "document_package":
        rel_path = f"exports/{export_id}.tar.gz"
    elif export_type.endswith("_csv"):
        rel_path = f"exports/{export_id}.csv"
    else:
        rel_path = f"exports/{export_id}.jsonl"

    abs_path = data_root / rel_path

    if export_type == "records_jsonl":
        record_count = _export_records_jsonl(conn, data_root, abs_path, filters)
    elif export_type == "records_csv":
        record_count = _export_records_csv(conn, abs_path, filters)
    elif export_type == "issues_csv":
        record_count = _export_issues_csv(conn, abs_path, filters)
    elif export_type == "audit_jsonl":
        record_count = _export_audit_jsonl(conn, abs_path, filters)
    elif export_type == "audit_csv":
        record_count = _export_audit_csv(conn, abs_path, filters)
    elif export_type == "provenance_jsonl":
        record_count = _export_provenance_jsonl(conn, abs_path, filters)
    elif export_type == "document_package":
        record_count = _export_document_package(conn, data_root, abs_path, filters)
    else:
        record_count = _export_records_jsonl(conn, data_root, abs_path, filters)

    byte_size = abs_path.stat().st_size
    with open(abs_path, "rb") as f:
        sha256_val = hash_stream(f)

    create_export_package(
        conn,
        export_id=export_id,
        export_type=export_type,
        relative_path=rel_path,
        sha256=sha256_val,
        byte_size=byte_size,
        record_count=record_count,
        filters_json=json.dumps(filters),
        created_by=actor,
        status="ready",
    )

    return {
        "export_id": export_id,
        "export_type": export_type,
        "relative_path": rel_path,
        "export_path": rel_path,
        "sha256": sha256_val,
        "byte_size": byte_size,
        "record_count": record_count,
        "status": "ready",
        "download_url": f"/api/exports/{export_id}/download",
    }


def _build_records_query(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    sql = """
        SELECT r.record_id, r.canonical_path, r.canonical_line, r.record_sha256
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        JOIN artifacts a ON v.artifact_id = a.artifact_id
        WHERE 1=1
    """
    params: list[Any] = []
    if filters.get("record_type"):
        sql += " AND r.record_type = ?"
        params.append(filters["record_type"])
    if filters.get("source") or filters.get("source_id"):
        sql += " AND a.source_id = ?"
        params.append(filters.get("source") or filters.get("source_id"))
    if filters.get("approval") or filters.get("approval_status"):
        sql += " AND r.approval_status = ?"
        params.append(filters.get("approval") or filters.get("approval_status"))
    if filters.get("validation") or filters.get("validation_status"):
        sql += " AND r.validation_status = ?"
        params.append(filters.get("validation") or filters.get("validation_status"))
    if filters.get("document") or filters.get("document_id"):
        sql += " AND v.document_id = ?"
        params.append(filters.get("document") or filters.get("document_id"))
    if filters.get("version") or filters.get("version_id"):
        sql += " AND r.version_id = ?"
        params.append(filters.get("version") or filters.get("version_id"))
    sql += " ORDER BY r.canonical_path ASC, r.canonical_line ASC"
    return sql, params


def _export_records_jsonl(conn: sqlite3.Connection, data_root: Path, out_path: Path, filters: dict[str, Any]) -> int:
    sql, params = _build_records_query(filters)
    cursor = conn.cursor()
    cursor.execute(sql, params)

    count = 0
    with open(out_path, "w", encoding="utf-8") as out_f:
        current_file_path = None
        current_file_handle = None

        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for r_id, rel_c_path, line_num, r_hash in rows:
                abs_c_path = data_root / rel_c_path
                if abs_c_path.exists():
                    if current_file_path != abs_c_path:
                        if current_file_handle is not None:
                            current_file_handle.close()
                        current_file_path = abs_c_path
                        current_file_handle = open(abs_c_path, "r", encoding="utf-8")

                    # Seek to beginning and scan to target line
                    current_file_handle.seek(0)
                    for idx, line_str in enumerate(current_file_handle, start=1):
                        if idx == line_num:
                            stripped = line_str.strip()
                            if stripped:
                                out_f.write(stripped + "\n")
                                count += 1
                            break

        if current_file_handle is not None:
            current_file_handle.close()

    return count


def _export_records_csv(conn: sqlite3.Connection, out_path: Path, filters: dict[str, Any]) -> int:
    sql = """
        SELECT r.record_id, r.record_type, r.version_id, r.approval_status, r.validation_status, 'Canonical Record' as title, '2026-01-01' as decision_date, r.record_sha256, r.created_at
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        JOIN artifacts a ON v.artifact_id = a.artifact_id
        WHERE 1=1
    """
    params: list[Any] = []
    if filters.get("record_type"):
        sql += " AND r.record_type = ?"
        params.append(filters["record_type"])
    if filters.get("approval") or filters.get("approval_status"):
        sql += " AND r.approval_status = ?"
        params.append(filters.get("approval") or filters.get("approval_status"))
    sql += " ORDER BY r.created_at DESC"

    cursor = conn.cursor()
    cursor.execute(sql, params)
    count = 0
    with open(out_path, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(["record_id", "record_type", "version_id", "approval_status", "validation_status", "title", "decision_date", "record_sha256", "created_at"])
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for r in rows:
                writer.writerow(list(r))
                count += 1
    return count


def _export_issues_csv(conn: sqlite3.Connection, out_path: Path, filters: dict[str, Any]) -> int:
    sql = "SELECT issue_id, subject_type, subject_id, severity, code, message, status, resolved_at, resolved_by, created_at FROM validation_issues WHERE 1=1"
    params: list[Any] = []
    if filters.get("status"):
        sql += " AND status = ?"
        params.append(filters["status"])
    if filters.get("severity"):
        sql += " AND severity = ?"
        params.append(filters["severity"])
    sql += " ORDER BY created_at DESC"

    cursor = conn.cursor()
    cursor.execute(sql, params)
    count = 0
    with open(out_path, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(["issue_id", "subject_type", "subject_id", "severity", "code", "message", "status", "resolved_at", "resolved_by", "created_at"])
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for r in rows:
                writer.writerow(list(r))
                count += 1
    return count


def _export_audit_jsonl(conn: sqlite3.Connection, out_path: Path, filters: dict[str, Any]) -> int:
    sql = "SELECT event_id, actor, action, subject_type, subject_id, old_sha256, new_sha256, reason, details_json, request_id, created_at FROM audit_events ORDER BY created_at DESC"
    cursor = conn.cursor()
    cursor.execute(sql)
    count = 0
    with open(out_path, "w", encoding="utf-8") as out_f:
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for r in rows:
                entry = {
                    "event_id": r[0],
                    "actor": r[1],
                    "action": r[2],
                    "subject_type": r[3],
                    "subject_id": r[4],
                    "old_sha256": r[5],
                    "new_sha256": r[6],
                    "reason": r[7],
                    "details": json.loads(r[8]) if r[8] else {},
                    "request_id": r[9],
                    "created_at": r[10],
                }
                out_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                count += 1
    return count


def _export_audit_csv(conn: sqlite3.Connection, out_path: Path, filters: dict[str, Any]) -> int:
    sql = "SELECT event_id, actor, action, subject_type, subject_id, old_sha256, new_sha256, reason, created_at FROM audit_events ORDER BY created_at DESC"
    cursor = conn.cursor()
    cursor.execute(sql)
    count = 0
    with open(out_path, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(["event_id", "actor", "action", "subject_type", "subject_id", "old_sha256", "new_sha256", "reason", "created_at"])
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for r in rows:
                writer.writerow(list(r))
                count += 1
    return count


def _export_provenance_jsonl(conn: sqlite3.Connection, out_path: Path, filters: dict[str, Any]) -> int:
    sql = "SELECT record_id FROM records ORDER BY created_at DESC"
    cursor = conn.cursor()
    cursor.execute(sql)
    count = 0
    with open(out_path, "w", encoding="utf-8") as out_f:
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for (r_id,) in rows:
                prov = get_record_provenance(r_id)
                if prov:
                    out_f.write(json.dumps(prov, ensure_ascii=False) + "\n")
                    count += 1
    return count


def _export_document_package(conn: sqlite3.Connection, data_root: Path, out_path: Path, filters: dict[str, Any]) -> int:
    doc_id = filters.get("document") or filters.get("document_id")
    sql = "SELECT document_id, canonical_path FROM versions"
    params: list[Any] = []
    if doc_id:
        sql += " WHERE document_id = ?"
        params.append(doc_id)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    count = 0
    with tarfile.open(out_path, "w:gz") as tar:
        for d_id, c_rel in rows:
            c_abs = data_root / c_rel
            if c_abs.exists():
                tar.add(c_abs, arcname=f"canonical/{c_abs.name}")
                count += 1
    return count
