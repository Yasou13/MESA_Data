import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from mesa_legal_data.audit import backup_catalog, run_doctor_check
from mesa_legal_data.catalog import (
    approve_record_with_checks,
    approve_version_with_checks,
    get_connection,
    get_db_path,
    get_document,
    get_record,
    list_open_blocking_issues,
    reject_record_with_checks,
)
from mesa_legal_data.config import load_settings, load_sources
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release import build_release, verify_release
from mesa_legal_data.release.importer import (
    get_record_provenance,
    get_staging_connection,
    import_release_to_staging,
    rollback_release,
)
from mesa_legal_data.sources import import_manual_file, import_manual_url
from mesa_legal_data.web.schemas import (
    ReleaseCreateRequest,
    ReviewRequest,
    RevokeRequest,
    UrlImportRequest,
)
from mesa_legal_data.web.security import verify_security, write_lock

router = APIRouter(prefix="/api", dependencies=[Depends(verify_security)])


def ok_response(data: Any = None) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def error_response(code: str, message: str, status_code: int = 400, details: Optional[Dict[str, Any]] = None):
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )


# 8.1 Health
@router.get("/health")
def health_check():
    db_path = get_db_path()
    catalog_ok = "ok" if db_path.exists() else "missing"
    settings = load_settings()
    data_root_ok = "ok" if settings.data_root_path.exists() else "missing"
    staging_ok = "ok" if Path(settings.mesa_staging_db).exists() else "missing"

    return ok_response(
        {
            "status": "ok",
            "catalog": catalog_ok,
            "data_root": data_root_ok,
            "staging": staging_ok,
            "version": "0.1.0",
        }
    )


# 8.2 Dashboard
@router.get("/dashboard")
def get_dashboard():
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT count(*) FROM documents")
    doc_count = c.fetchone()[0]

    c.execute("SELECT count(*) FROM artifacts")
    art_count = c.fetchone()[0]

    c.execute("SELECT count(*) FROM records")
    record_count = c.fetchone()[0]

    c.execute("SELECT count(*) FROM records WHERE approval_status = 'pending'")
    pending_review_count = c.fetchone()[0]

    c.execute("SELECT count(*) FROM records WHERE approval_status = 'approved'")
    approved_record_count = c.fetchone()[0]

    c.execute("SELECT count(*) FROM validation_issues WHERE status = 'open' AND severity = 'blocker'")
    open_blockers = c.fetchone()[0]

    c.execute("SELECT count(*) FROM validation_issues WHERE status = 'open' AND severity = 'error'")
    open_errors = c.fetchone()[0]

    c.execute("SELECT count(*) FROM releases WHERE status = 'published'")
    published_releases = c.fetchone()[0]

    c.execute(
        "SELECT document_id, family, document_type, title, lifecycle_status, updated_at FROM documents ORDER BY updated_at DESC LIMIT 10"
    )
    recent_docs = [
        {"document_id": r[0], "family": r[1], "document_type": r[2], "title": r[3], "status": r[4], "updated_at": r[5]}
        for r in c.fetchall()
    ]

    c.execute(
        "SELECT run_id, command, status, started_at, finished_at FROM processing_runs ORDER BY started_at DESC LIMIT 10"
    )
    recent_runs = [
        {"run_id": r[0], "command": r[1], "status": r[2], "started_at": r[3], "finished_at": r[4]} for r in c.fetchall()
    ]

    conn.close()

    # Active MESA Release in staging
    active_release_id = None
    try:
        stg_conn = get_staging_connection()
        stg_cur = stg_conn.cursor()
        stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
        row = stg_cur.fetchone()
        if row:
            active_release_id = row[0]
        stg_conn.close()
    except Exception:
        pass

    return ok_response(
        {
            "counts": {
                "documents": doc_count,
                "artifacts": art_count,
                "records": record_count,
                "pending_reviews": pending_review_count,
                "approved_records": approved_record_count,
                "open_blockers": open_blockers,
                "open_errors": open_errors,
                "published_releases": published_releases,
                "active_release_id": active_release_id,
            },
            "recent_documents": recent_docs,
            "recent_runs": recent_runs,
        }
    )


# 8.3 Public Config
@router.get("/config/public")
def get_public_config():
    settings = load_settings()
    sources_yaml_path = Path(__file__).parent.parent.parent.parent / "config" / "sources.yaml"
    enabled_sources = []
    if sources_yaml_path.exists():
        src_cfg = load_sources(sources_yaml_path)
        for s_id, s_info in src_cfg.sources.items():
            enabled_sources.append(
                {"source_id": s_id, "name": s_info.name, "enabled": s_info.enabled, "authority": s_info.authority}
            )

    return ok_response(
        {
            "environment": settings.environment,
            "data_root": str(settings.data_root_path),
            "app_version": "0.1.0",
            "enabled_sources": enabled_sources,
            "storage": settings.storage.model_dump(),
        }
    )


# 8.4 Documents
@router.get("/documents")
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    family: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
):
    conn = get_connection()
    c = conn.cursor()

    where_clauses = []
    params = []

    if status:
        where_clauses.append("d.lifecycle_status = ?")
        params.append(status)
    if family:
        where_clauses.append("d.family = ?")
        params.append(family)
    if q:
        where_clauses.append("(d.document_id LIKE ? OR d.title LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    c.execute(f"SELECT count(*) FROM documents d {where_sql}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * page_size
    query = f"""
        SELECT d.document_id, d.family, d.document_type, d.jurisdiction, d.title, d.stable_key, d.lifecycle_status, d.current_version_id, d.updated_at,
               (SELECT count(*) FROM artifacts a WHERE a.document_id = d.document_id) as art_count
        FROM documents d
        {where_sql}
        ORDER BY d.updated_at DESC
        LIMIT ? OFFSET ?
    """
    c.execute(query, params + [page_size, offset])
    items = []
    for r in c.fetchall():
        items.append(
            {
                "document_id": r[0],
                "family": r[1],
                "document_type": r[2],
                "jurisdiction": r[3],
                "title": r[4],
                "stable_key": r[5],
                "lifecycle_status": r[6],
                "current_version_id": r[7],
                "updated_at": r[8],
                "artifact_count": r[9],
            }
        )

    conn.close()
    return ok_response(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/documents/{document_id:path}")
def get_document_detail(document_id: str):
    conn = get_connection()
    doc = get_document(conn, document_id)
    if not doc:
        conn.close()
        error_response("DOCUMENT_NOT_FOUND", f"Document {document_id} not found", status_code=404)

    doc_data = dict(doc or {})
    c = conn.cursor()
    c.execute(
        "SELECT artifact_id, source_id, source_url, retrieved_at, transport_status, sha256 FROM artifacts WHERE document_id = ?",
        (document_id,),
    )
    artifacts = [
        {
            "artifact_id": r[0],
            "source_id": r[1],
            "source_url": r[2],
            "retrieved_at": r[3],
            "transport_status": r[4],
            "sha256": r[5],
        }
        for r in c.fetchall()
    ]

    c.execute(
        "SELECT issue_id, severity, code, message, status FROM validation_issues WHERE subject_id = ? AND status = 'open'",
        (document_id,),
    )
    issues = [{"issue_id": r[0], "severity": r[1], "code": r[2], "message": r[3], "status": r[4]} for r in c.fetchall()]

    conn.close()
    doc_data["artifacts"] = artifacts
    doc_data["open_issues"] = issues
    return ok_response(doc_data)


# 8.5 Artifacts
@router.post("/artifacts/upload")
async def upload_artifact(
    file: UploadFile = File(...),
    source_id: str = Form(...),
    document_id: str = Form(...),
    family: str = Form("legislation"),
    document_type: str = Form("law"),
    jurisdiction: str = Form("TR"),
    title: Optional[str] = Form(None),
):
    async with write_lock.acquire_write():
        settings = load_settings()
        temp_dir = settings.data_root_path / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"upload_{uuid.uuid4().hex}_{file.filename}"

        try:
            downloaded = 0
            max_bytes = 50 * 1024 * 1024
            with open(temp_path, "wb") as buffer:
                while chunk := await file.read(8192):
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        error_response("FILE_TOO_LARGE", f"File exceeds limit of {max_bytes} bytes", status_code=413)
                    buffer.write(chunk)

            art = import_manual_file(
                source_id=source_id,
                file_path=temp_path,
                document_id=document_id,
                family=family,
                document_type=document_type,
                jurisdiction=jurisdiction,
                title=title,
            )
            return ok_response({"artifact_id": art.artifact_id, "raw_path": art.raw_path, "sha256": art.sha256})
        except Exception as e:
            error_response("UPLOAD_FAILED", f"Upload failed: {e}", status_code=400)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)


@router.post("/artifacts/from-url")
def import_from_url(req: UrlImportRequest):
    try:
        art = import_manual_url(
            source_id=req.source_id,
            url=req.url,
            document_id=req.document_id,
            family=req.family,
            document_type=req.document_type,
            jurisdiction=req.jurisdiction,
            title=req.title,
        )
        return ok_response({"artifact_id": art.artifact_id, "raw_path": art.raw_path, "sha256": art.sha256})
    except Exception as e:
        error_response("URL_IMPORT_FAILED", str(e), status_code=400)


@router.post("/artifacts/{artifact_id}/process")
async def process_artifact(artifact_id: str):
    async with write_lock.acquire_write():
        try:
            pipeline_status = process_artifact_pipeline(artifact_id=artifact_id)
            return ok_response({"artifact_id": artifact_id, "pipeline_status": pipeline_status})
        except Exception as e:
            error_response("PIPELINE_FAILED", f"Pipeline failed: {e}", status_code=400)


# 8.6 Records
@router.get("/records")
def list_records(
    approval_status: Optional[str] = Query(None),
    record_type: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    conn = get_connection()
    c = conn.cursor()

    where_clauses = []
    params = []
    if approval_status:
        where_clauses.append("r.approval_status = ?")
        params.append(approval_status)
    if record_type:
        where_clauses.append("r.record_type = ?")
        params.append(record_type)
    if document_id:
        where_clauses.append("v.document_id = ?")
        params.append(document_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    c.execute(f"SELECT count(*) FROM records r JOIN versions v ON r.version_id = v.version_id {where_sql}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * page_size
    query = f"""
        SELECT r.record_id, r.version_id, r.record_type, r.canonical_path, r.canonical_line, r.record_sha256, r.validation_status, r.approval_status, r.created_at, v.document_id
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        {where_sql}
        ORDER BY r.created_at DESC
        LIMIT ? OFFSET ?
    """
    c.execute(query, params + [page_size, offset])
    items = []
    for row in c.fetchall():
        items.append(
            {
                "record_id": row[0],
                "version_id": row[1],
                "record_type": row[2],
                "canonical_path": row[3],
                "canonical_line": row[4],
                "record_sha256": row[5],
                "validation_status": row[6],
                "approval_status": row[7],
                "created_at": row[8],
                "document_id": row[9],
            }
        )

    conn.close()
    return ok_response({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/records/{record_id:path}")
def get_record_detail(record_id: str):
    conn = get_connection()
    rec = get_record(conn, record_id)
    if not rec:
        conn.close()
        error_response("RECORD_NOT_FOUND", f"Record {record_id} not found", status_code=404)

    rec_data = dict(rec or {})
    # Read canonical line preview (up to 20,000 chars)
    settings = load_settings()
    c_abs_path = settings.data_root_path / str(rec_data["canonical_path"])
    text_preview = None
    if c_abs_path.exists():
        with open(c_abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        line_idx = int(rec_data["canonical_line"]) - 1
        if 0 <= line_idx < len(lines):
            text_preview = lines[line_idx][:20000]

    blockers = list_open_blocking_issues(conn, subject_id=record_id)
    conn.close()

    rec_data["text_preview"] = text_preview
    rec_data["open_blockers"] = blockers
    return ok_response(rec_data)


# 8.7 Review
@router.post("/records/{record_id:path}/approve")
async def approve_record(record_id: str, req: ReviewRequest):
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            res = approve_record_with_checks(conn, record_id, req.reviewer, req.note)
            return ok_response(res)
        except Exception as e:
            error_response("REVIEW_FAILED", str(e), status_code=400)
        finally:
            conn.close()


@router.post("/records/{record_id:path}/reject")
async def reject_record(record_id: str, req: ReviewRequest):
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            res = reject_record_with_checks(conn, record_id, req.reviewer, req.note)
            return ok_response(res)
        except Exception as e:
            error_response("REVIEW_FAILED", str(e), status_code=400)
        finally:
            conn.close()


@router.post("/versions/{version_id:path}/approve")
async def approve_version(version_id: str, req: ReviewRequest):
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            res = approve_version_with_checks(conn, version_id, req.reviewer, req.note)
            return ok_response(res)
        except Exception as e:
            error_response("VERSION_APPROVE_FAILED", str(e), status_code=400)
        finally:
            conn.close()


# 8.8 Issues
@router.get("/issues")
def list_issues(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[str] = Query(None),
):
    conn = get_connection()
    c = conn.cursor()

    where_clauses = []
    params = []
    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if severity:
        where_clauses.append("severity = ?")
        params.append(severity)
    if subject_type:
        where_clauses.append("subject_type = ?")
        params.append(subject_type)
    if subject_id:
        where_clauses.append("subject_id = ?")
        params.append(subject_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    c.execute(
        f"SELECT issue_id, subject_type, subject_id, severity, code, message, status, opened_at FROM validation_issues {where_sql} ORDER BY opened_at DESC",
        params,
    )
    issues = [
        {
            "issue_id": r[0],
            "subject_type": r[1],
            "subject_id": r[2],
            "severity": r[3],
            "code": r[4],
            "message": r[5],
            "status": r[6],
            "opened_at": r[7],
        }
        for r in c.fetchall()
    ]
    conn.close()
    return ok_response(issues)


# 8.9 Releases
@router.get("/releases")
def list_releases():
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT release_id, release_path, status, schema_version, created_at, published_at, counts_json, manifest_sha256 FROM releases ORDER BY created_at DESC"
    )
    releases = [
        {
            "release_id": r[0],
            "release_path": r[1],
            "status": r[2],
            "schema_version": r[3],
            "created_at": r[4],
            "published_at": r[5],
            "counts": json.loads(r[6]) if r[6] else {},
            "manifest_sha256": r[7],
        }
        for r in c.fetchall()
    ]
    conn.close()
    return ok_response(releases)


@router.post("/releases")
async def create_release_endpoint(req: ReleaseCreateRequest):
    async with write_lock.acquire_write():
        try:
            rel_meta = build_release(release_id=req.release_id)
            return ok_response(rel_meta)
        except Exception as e:
            error_response("RELEASE_BUILD_FAILED", str(e), status_code=400)


@router.post("/releases/{release_id}/verify")
def verify_release_endpoint(release_id: str):
    try:
        res = verify_release(release_id)
        return ok_response({"release_id": release_id, "verified": res})
    except Exception as e:
        error_response("RELEASE_VERIFY_FAILED", str(e), status_code=400)


@router.post("/releases/{release_id}/publish")
async def publish_release_endpoint(release_id: str):
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            verify_release(release_id)
            conn.execute("UPDATE releases SET status = 'published' WHERE release_id = ?", (release_id,))
            return ok_response({"release_id": release_id, "status": "published"})
        except Exception as e:
            error_response("RELEASE_PUBLISH_FAILED", str(e), status_code=400)
        finally:
            conn.close()


@router.post("/releases/{release_id}/import")
async def import_release_endpoint(release_id: str):
    async with write_lock.acquire_write():
        try:
            res = import_release_to_staging(release_id)
            return ok_response(res)
        except Exception as e:
            error_response("RELEASE_IMPORT_FAILED", str(e), status_code=400)


@router.post("/releases/{release_id}/rollback")
async def rollback_release_endpoint(release_id: str):
    async with write_lock.acquire_write():
        try:
            res = rollback_release(release_id)
            return ok_response(res)
        except Exception as e:
            error_response("RELEASE_ROLLBACK_FAILED", str(e), status_code=400)


@router.post("/releases/{release_id}/revoke")
async def revoke_release_endpoint(release_id: str, req: RevokeRequest):
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            conn.execute("UPDATE releases SET status = 'revoked' WHERE release_id = ?", (release_id,))
            return ok_response({"release_id": release_id, "status": "revoked", "reason": req.reason})
        except Exception as e:
            error_response("RELEASE_REVOKE_FAILED", str(e), status_code=400)
        finally:
            conn.close()


# 8.10 Provenance
@router.get("/provenance/{record_id:path}")
def get_provenance(record_id: str):
    prov = get_record_provenance(record_id)
    if not prov:
        error_response("PROVENANCE_NOT_FOUND", f"Provenance not found for record {record_id}", status_code=404)
    return ok_response(prov)


# 8.11 System
@router.get("/system/status")
def system_status():
    doc_res = run_doctor_check()
    return ok_response(doc_res)


@router.post("/system/doctor")
def run_doctor():
    res = run_doctor_check()
    return ok_response(res)


@router.post("/system/backup")
async def run_backup():
    async with write_lock.acquire_write():
        try:
            b_path = backup_catalog()
            try:
                rel_b_path = str(b_path.relative_to(load_settings().data_root_path))
            except ValueError:
                rel_b_path = str(b_path)
            return ok_response({"backup_path": rel_b_path})
        except Exception as e:
            error_response("BACKUP_FAILED", str(e), status_code=400)
