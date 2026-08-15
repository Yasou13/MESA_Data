import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from mesa_legal_data.audit import backup_catalog, log_audit_event, run_doctor_check
from mesa_legal_data.catalog import (
    BlockingValidationIssueExists,
    approve_record_with_checks,
    approve_version_streaming,
    get_artifact,
    get_connection,
    get_db_path,
    get_document,
    get_export_package,
    get_record,
    get_release,
    list_open_blocking_issues,
    reject_record_with_checks,
    resolve_issue,
)
from mesa_legal_data.config import load_settings, load_sources
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release import build_release, verify_release
from mesa_legal_data.release.importer import (
    ReleaseNotFound,
    ReleaseNotPublished,
    ReleaseRevoked,
    ReleaseStateChanged,
    get_record_provenance,
    get_staging_connection,
    import_release_to_staging,
    rollback_release,
)
from mesa_legal_data.sources import import_manual_file, import_manual_url
from mesa_legal_data.web.schemas import (
    HarvestStartRequest,
    IssueResolveRequest,
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
@router.get("/dashboard/stats")
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

    from mesa_legal_data.harvest.reporting import get_harvest_dashboard_summary

    harvest_summary = get_harvest_dashboard_summary()

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
            "harvest": harvest_summary,
        }
    )


# --- HARVEST ENDPOINTS ---


@router.get("/harvest/status")
def get_harvest_status_endpoint():
    from datetime import date, datetime

    from mesa_legal_data.harvest.config import load_harvest_config
    from mesa_legal_data.harvest.database import get_harvest_connection, get_harvest_db_path
    from mesa_legal_data.harvest.discovery_state import get_discovery_cursor
    from mesa_legal_data.harvest.reporting import get_harvest_status_summary

    settings = load_settings()
    data_root = settings.data_root_path
    db_path = get_harvest_db_path(custom_data_root=data_root)

    # Check active operation job
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT operation_id, status, error_summary FROM operation_jobs WHERE operation_type = 'harvest_collection' AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1"
    )
    active_op_row = c.fetchone()
    conn.close()

    active_op_id = active_op_row[0] if active_op_row else None
    active_op_status = active_op_row[1] if active_op_row else None

    if not db_path.exists():
        return ok_response(
            {
                "state": "not_started",
                "initialized": False,
                "source_id": "resmi_gazete",
                "source_name": "T.C. Resmî Gazete",
                "mode": None,
                "start_date": "2015-01-01",
                "cursor_date": None,
                "coverage_percent": 0,
                "total_items": 0,
                "queued": 0,
                "completed": 0,
                "needs_review": 0,
                "retry_wait": 0,
                "failed": 0,
                "blocked": 0,
                "duplicate": 0,
                "last_discovery_at": None,
                "last_discovery_status": None,
                "active_operation_id": active_op_id,
                "active_operation_status": active_op_status,
                "message": "Henüz veri toplama başlatılmadı.",
            }
        )

    cfg = load_harvest_config()
    src_cfg = cfg.sources.get("resmi_gazete")
    start_date_str = (src_cfg.date_from if src_cfg else None) or "2015-01-01"

    summary = get_harvest_status_summary(db_path=db_path)
    status_counts = summary.get("status_counts", {})
    total_items = summary.get("total_items", 0)

    # Last discovery info
    h_conn = get_harvest_connection(db_path)
    last_discovery_status = None
    last_discovery_at = None
    try:
        hc = h_conn.cursor()
        hc.execute(
            "SELECT status, started_at FROM discovery_runs WHERE source_id = 'resmi_gazete' ORDER BY started_at DESC LIMIT 1"
        )
        d_row = hc.fetchone()
        if d_row:
            last_discovery_status = d_row["status"]
            last_discovery_at = d_row["started_at"]
    finally:
        h_conn.close()

    cursor_data = get_discovery_cursor("resmi_gazete", db_path=db_path) or {}
    mode = cursor_data.get("mode")
    cursor_date_str = (
        cursor_data.get("last_successful_date") or cursor_data.get("backfill_next_date") or cursor_data.get("next_date")
    )

    # Date coverage calculation
    coverage_percent = 0
    today = date.today()
    try:
        start_d = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        total_span = (today - start_d).days
        if total_span > 0:
            if mode == "incremental" or (
                mode == "backfill" and cursor_data.get("backfill_next_date") is None and cursor_date_str
            ):
                coverage_percent = 100
            elif cursor_date_str:
                curr_d = datetime.strptime(cursor_date_str, "%Y-%m-%d").date()
                traversed = (today - curr_d).days
                coverage_percent = min(100, max(0, int((traversed / total_span) * 100)))
    except Exception:
        coverage_percent = 0

    queued = status_counts.get("queued", 0) + status_counts.get("leased", 0)
    completed = status_counts.get("completed", 0)
    needs_review = status_counts.get("needs_review", 0)
    retry_wait = status_counts.get("retry_wait", 0)
    failed = status_counts.get("failed", 0)
    blocked = status_counts.get("blocked", 0)
    duplicate = status_counts.get("duplicate", 0)

    # State computation
    if active_op_status in ("queued", "running"):
        state = "running"
        if mode == "incremental":
            message = "Güncel Resmî Gazete verileri kontrol ediliyor."
        elif cursor_date_str:
            message = f"Resmî Gazete geçmiş verileri toplanıyor (Şu anda {cursor_date_str} civarı taranıyor)."
        else:
            message = "Resmî Gazete veri toplama işlemi devam ediyor."
    elif failed > 0 or last_discovery_status == "failed":
        state = "attention"
        message = "Toplama sırasında dikkat gerektiren sorunlar oluştu."
    elif total_items == 0 and not last_discovery_at:
        state = "not_started"
        message = "Henüz veri toplama başlatılmadı."
    elif queued == 0 and mode == "incremental":
        state = "up_to_date"
        message = "Resmî Gazete verileri güncel görünüyor."
    else:
        state = "paused"
        message = "Veri toplama duraklatıldı."

    return ok_response(
        {
            "state": state,
            "initialized": True,
            "source_id": "resmi_gazete",
            "source_name": "T.C. Resmî Gazete",
            "mode": mode,
            "start_date": start_date_str,
            "cursor_date": cursor_date_str,
            "coverage_percent": coverage_percent,
            "total_items": total_items,
            "queued": queued,
            "completed": completed,
            "needs_review": needs_review,
            "retry_wait": retry_wait,
            "failed": failed,
            "blocked": blocked,
            "duplicate": duplicate,
            "last_discovery_at": last_discovery_at,
            "last_discovery_status": last_discovery_status,
            "active_operation_id": active_op_id,
            "active_operation_status": active_op_status,
            "message": message,
        }
    )


@router.post("/harvest/start")
async def start_harvest_endpoint(req: HarvestStartRequest, request: Request):
    from datetime import date, datetime

    from mesa_legal_data.operations import submit_operation

    if req.source_id != "resmi_gazete":
        error_response(
            "SOURCE_NOT_SUPPORTED",
            f"Otomatik veri toplama şu anda yalnızca 'resmi_gazete' için desteklenmektedir. '{req.source_id}' için manuel ekleme kullanınız.",
            status_code=400,
        )

    if req.start_date:
        try:
            s_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
            if s_date > date.today():
                error_response("INVALID_START_DATE", "Başlangıç tarihi gelecekte olamaz.", status_code=400)
        except ValueError:
            error_response("INVALID_START_DATE", "Başlangıç tarihi YYYY-AA-GG biçiminde olmalıdır.", status_code=400)

    allowed_types = {"law", "presidential_decree", "presidential_decision", "regulation", "communique"}
    if req.document_types is not None:
        if len(req.document_types) == 0:
            error_response("INVALID_DOCUMENT_TYPES", "En az bir belge türü seçilmelidir.", status_code=400)
        invalid = [t for t in req.document_types if t not in allowed_types]
        if invalid:
            error_response("INVALID_DOCUMENT_TYPES", f"Desteklenmeyen belge türleri: {invalid}", status_code=400)

    actor = extract_actor(request)
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT operation_id FROM operation_jobs WHERE operation_type = 'harvest_collection' AND status IN ('queued', 'running')"
            )
            running_op = c.fetchone()
            if running_op:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "HARVEST_ALREADY_RUNNING", "message": "Veri toplama zaten devam ediyor."},
                )

            input_dict = {
                "source_id": req.source_id,
                "start_date": req.start_date,
                "document_types": req.document_types,
            }
            op_id = submit_operation(
                conn,
                operation_type="harvest_collection",
                requested_by=actor,
                input_dict=input_dict,
            )
            return ok_response({"operation_id": op_id, "status": "submitted"})
        finally:
            conn.close()


@router.post("/harvest/stop")
async def stop_harvest_endpoint(request: Request):
    from mesa_legal_data.operations import cancel_operation

    actor = extract_actor(request)
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT operation_id FROM operation_jobs WHERE operation_type = 'harvest_collection' AND status IN ('queued', 'running')"
            )
            row = c.fetchone()
            if not row:
                return ok_response({"status": "not_running"})

            op_id = row[0]
            cancel_operation(conn, op_id, actor=actor)
            return ok_response({"operation_id": op_id, "status": "cancelled"})
        finally:
            conn.close()


# 8.3 Public Config & Sources
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


@router.get("/sources")
def list_sources_endpoint():
    sources_yaml_path = Path(__file__).parent.parent.parent.parent / "config" / "sources.yaml"
    sources_list = []
    if sources_yaml_path.exists():
        src_cfg = load_sources(sources_yaml_path)
        for s_id, s_info in src_cfg.sources.items():
            if s_id == "resmi_gazete" and s_info.enabled:
                automation = "supported"
            elif not s_info.enabled:
                automation = "disabled"
            else:
                automation = "manual"
            sources_list.append(
                {
                    "source_id": s_id,
                    "name": s_info.name,
                    "authority": s_info.authority,
                    "base_url": s_info.base_url,
                    "access_mode": s_info.access_mode,
                    "enabled": s_info.enabled,
                    "families": s_info.families,
                    "automation": automation,
                }
            )
    return ok_response(sources_list)


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
    if source:
        where_clauses.append("d.document_id IN (SELECT a.document_id FROM artifacts a WHERE a.source_id = ?)")
        params.append(source)
    if q:
        where_clauses.append("(d.document_id LIKE ? OR d.title LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    c.execute(f"SELECT count(*) FROM documents d {where_sql}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * page_size
    query = f"""
        SELECT d.document_id, d.family, d.document_type, d.jurisdiction, d.title, d.stable_key, d.lifecycle_status, d.current_version_id, d.updated_at,
               (SELECT count(*) FROM artifacts a WHERE a.document_id = d.document_id) as art_count,
               (SELECT a.source_id FROM artifacts a WHERE a.document_id = d.document_id ORDER BY a.retrieved_at DESC LIMIT 1) as source_id
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
                "source_id": r[10] or "unknown",
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


def extract_actor(request: Request) -> str:
    actor = request.headers.get("X-MESA-Actor") or request.headers.get("X-Actor")
    if not actor:
        actor = request.query_params.get("actor") or "web-user"
    return actor.strip()


def validate_file_download(
    data_root: Path,
    rel_or_abs_path: str | Path,
    expected_sha256: str | None = None,
) -> Path:
    from mesa_legal_data.downloads import resolve_verified_download

    return resolve_verified_download(
        relative_path=rel_or_abs_path,
        expected_sha256=expected_sha256,
        data_root=data_root,
    )


@router.get("/artifacts/{artifact_id}/download")
def download_artifact_endpoint(artifact_id: str, request: Request):
    from fastapi.responses import FileResponse

    actor = extract_actor(request)
    conn = get_connection()
    art = get_artifact(conn, artifact_id)
    if not art:
        conn.close()
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": f"Artifact {artifact_id} not found"}
        )

    data_root = load_settings().data_root_path
    safe_path = validate_file_download(data_root, art["raw_path"], expected_sha256=art.get("sha256"))

    log_audit_event(
        conn,
        actor=actor,
        action="download_artifact",
        subject_type="artifact",
        subject_id=artifact_id,
        new_sha256=art.get("sha256"),
    )
    conn.close()

    media_type = art.get("detected_content_type") or "application/octet-stream"
    safe_filename = Path(art["raw_path"]).name
    return FileResponse(
        path=str(safe_path),
        media_type=media_type,
        filename=safe_filename,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.get("/artifacts/{artifact_id}/metadata/download")
def download_artifact_metadata_endpoint(artifact_id: str, request: Request):
    from fastapi.responses import Response

    actor = extract_actor(request)
    conn = get_connection()
    art = get_artifact(conn, artifact_id)
    if not art:
        conn.close()
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": f"Artifact {artifact_id} not found"}
        )

    log_audit_event(
        conn,
        actor=actor,
        action="download_artifact_metadata",
        subject_type="artifact",
        subject_id=artifact_id,
    )
    conn.close()

    content = json.dumps(art, indent=2, ensure_ascii=False)
    safe_filename = f"artifact_{artifact_id}_metadata.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.get("/records/{record_id}/download")
def download_record_endpoint(record_id: str, request: Request, format: str = Query("json")):
    from fastapi.responses import Response

    actor = extract_actor(request)
    conn = get_connection()
    rec = get_record(conn, record_id)
    if not rec:
        conn.close()
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Record {record_id} not found"})

    data_root = load_settings().data_root_path
    safe_path = validate_file_download(data_root, rec["canonical_path"])

    target_line = None
    with open(safe_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            if idx == rec["canonical_line"]:
                target_line = line
                break

    if not target_line:
        conn.close()
        raise HTTPException(status_code=404, detail={"code": "LINE_NOT_FOUND", "message": "Canonical line missing"})

    calc_hash = hashlib.sha256(target_line.encode("utf-8")).hexdigest()
    if rec.get("record_sha256") and calc_hash.lower() != rec["record_sha256"].lower():
        conn.close()
        raise HTTPException(
            status_code=400, detail={"code": "HASH_MISMATCH", "message": "Record SHA-256 hash mismatch"}
        )

    log_audit_event(
        conn,
        actor=actor,
        action="download_record",
        subject_type="record",
        subject_id=record_id,
        new_sha256=rec.get("record_sha256"),
    )
    conn.close()

    rec_obj = json.loads(target_line)
    if format == "text":
        out_content = rec_obj.get("text") or rec_obj.get("title") or target_line
        media_type = "text/plain"
        ext = "txt"
    else:
        out_content = json.dumps(rec_obj, indent=2, ensure_ascii=False)
        media_type = "application/json"
        ext = "json"

    safe_filename = f"record_{record_id}.{ext}"
    return Response(
        content=out_content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.get("/provenance/{record_id}/download")
def download_provenance_endpoint(record_id: str, request: Request):
    from fastapi.responses import Response

    actor = extract_actor(request)
    conn = get_connection()
    prov = get_record_provenance(record_id)
    if not prov:
        conn.close()
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": f"Provenance for record {record_id} not found"}
        )

    log_audit_event(
        conn,
        actor=actor,
        action="download_provenance",
        subject_type="record",
        subject_id=record_id,
    )
    conn.close()

    content = json.dumps(prov, indent=2, ensure_ascii=False)
    safe_filename = f"provenance_{record_id}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.get("/releases/{release_id:path}/download")
def download_release_endpoint(release_id: str, request: Request):
    from fastapi.responses import FileResponse

    actor = extract_actor(request)
    conn = get_connection()
    rel = get_release(conn, release_id)
    if not rel:
        conn.close()
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Release {release_id} not found"})

    data_root = load_settings().data_root_path
    rel_manifest = Path(rel["release_path"]) / "manifest.json"
    safe_manifest = validate_file_download(data_root, rel_manifest, expected_sha256=rel.get("manifest_sha256"))

    log_audit_event(
        conn,
        actor=actor,
        action="download_release",
        subject_type="release",
        subject_id=release_id,
        new_sha256=rel.get("manifest_sha256"),
    )
    conn.close()

    safe_filename = f"{Path(release_id).name}_manifest.json"
    return FileResponse(
        path=str(safe_manifest),
        media_type="application/json",
        filename=safe_filename,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.get("/documents/{document_id:path}/download/raw")
def download_raw(document_id: str, request: Request, inline: bool = Query(True)):
    from fastapi.responses import FileResponse

    actor = extract_actor(request)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT artifact_id, raw_path, detected_content_type, sha256 FROM artifacts WHERE document_id = ? ORDER BY retrieved_at DESC LIMIT 1",
        (document_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Raw artifact for document '{document_id}' not found"},
        )
    art_id, raw_rel, media_type, sha = row

    data_root = load_settings().data_root_path
    safe_path = validate_file_download(data_root, raw_rel, expected_sha256=sha)

    log_audit_event(
        conn,
        actor=actor,
        action="download_raw_document",
        subject_type="document",
        subject_id=document_id,
        new_sha256=sha,
    )
    conn.close()

    safe_filename = Path(raw_rel).name
    disp = "inline" if inline else "attachment"
    return FileResponse(
        path=str(safe_path),
        media_type=media_type or "text/html",
        filename=safe_filename,
        headers={"Content-Disposition": f'{disp}; filename="{safe_filename}"'},
    )


@router.get("/documents/{document_id:path}/download/canonical")
def download_canonical(document_id: str, request: Request, inline: bool = Query(True)):
    from fastapi.responses import FileResponse

    actor = extract_actor(request)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT version_id, canonical_path FROM versions WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
        (document_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Canonical version for document {document_id} not found"},
        )
    ver_id, rel_p = row

    data_root = load_settings().data_root_path
    safe_path = validate_file_download(data_root, rel_p)

    log_audit_event(
        conn,
        actor=actor,
        action="download_canonical_document",
        subject_type="document",
        subject_id=document_id,
    )
    conn.close()

    safe_filename = Path(rel_p).name
    disp = "inline" if inline else "attachment"
    return FileResponse(
        path=str(safe_path),
        media_type="text/plain; charset=utf-8",
        filename=safe_filename,
        headers={"Content-Disposition": f'{disp}; filename="{safe_filename}"'},
    )


@router.get("/documents/{document_id:path}/text")
def get_document_text_content(document_id: str):
    conn = get_connection()
    doc = get_document(conn, document_id)
    if not doc:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Document '{document_id}' not found"},
        )

    c = conn.cursor()
    c.execute(
        "SELECT raw_path FROM artifacts WHERE document_id = ? ORDER BY retrieved_at DESC LIMIT 1",
        (document_id,),
    )
    row = c.fetchone()
    raw_path_rel = row[0] if row else None

    data_root = load_settings().data_root_path
    content_text = ""
    source_type = "raw"

    if raw_path_rel:
        try:
            safe_p = validate_file_download(data_root, raw_path_rel)
            content_text = safe_p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass

    if not content_text:
        c.execute(
            "SELECT canonical_path FROM versions WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
            (document_id,),
        )
        v_row = c.fetchone()
        if v_row and v_row[0]:
            try:
                safe_can = validate_file_download(data_root, v_row[0])
                content_text = safe_can.read_text(encoding="utf-8", errors="ignore")
                source_type = "canonical"
            except Exception:
                pass

    conn.close()

    truncated = False
    if len(content_text) > 200000:
        content_text = content_text[:200000] + "\n... [Metin 200 KB sınırı nedeniyle kesildi] ..."
        truncated = True

    return ok_response(
        {
            "document_id": document_id,
            "title": dict(doc).get("title"),
            "source_type": source_type,
            "truncated": truncated,
            "content": content_text or "Metin içeriği bulunamadı.",
        }
    )


SOURCE_FAMILY_MAP = {
    "resmi_gazete": "legislation",
    "mevzuat": "legislation",
    "aym": "decision",
    "yargitay": "decision",
}


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
        "SELECT artifact_id, source_id, source_url, retrieved_at, transport_status, sha256, raw_path FROM artifacts WHERE document_id = ?",
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
            "raw_path": r[6],
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
    doc_data["source_id"] = artifacts[0]["source_id"] if artifacts else "unknown"
    doc_data["open_issues"] = issues
    return ok_response(doc_data)


# 8.5 Artifacts
@router.post("/artifacts/upload")
@router.post("/manual/upload-file")
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

            # Map correct family based on source capability if client passed default
            effective_family = SOURCE_FAMILY_MAP.get(source_id, family)
            if family != "legislation" and family in ("legislation", "decision"):
                effective_family = family

            art = import_manual_file(
                source_id=source_id,
                file_path=temp_path,
                document_id=document_id,
                family=effective_family,
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
@router.post("/manual/import-url")
@router.post("/documents/import-url")
def import_from_url(req: UrlImportRequest):
    try:
        effective_family = SOURCE_FAMILY_MAP.get(req.source_id, req.family)
        if req.family != "legislation" and req.family in ("legislation", "decision"):
            effective_family = req.family

        art = import_manual_url(
            source_id=req.source_id,
            url=req.url,
            document_id=req.document_id,
            family=effective_family,
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


@router.post("/documents/{document_id:path}/pipeline")
async def process_document_pipeline(document_id: str):
    async with write_lock.acquire_write():
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT artifact_id FROM artifacts WHERE document_id = ? ORDER BY retrieved_at DESC LIMIT 1",
            (document_id,),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            error_response("ARTIFACT_NOT_FOUND", f"No artifact found for document {document_id}", status_code=404)
        artifact_id = row[0]
        try:
            pipeline_status = process_artifact_pipeline(artifact_id=artifact_id)
            return ok_response(
                {"document_id": document_id, "artifact_id": artifact_id, "pipeline_status": pipeline_status}
            )
        except Exception as e:
            error_response("PIPELINE_FAILED", f"Pipeline failed: {e}", status_code=400)


# 8.6 Records
@router.get("/records")
@router.get("/reviews/records")
def list_records(
    approval_status: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    record_type: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    conn = get_connection()
    c = conn.cursor()

    target_status = approval_status or status
    where_clauses = []
    params = []
    if target_status:
        where_clauses.append("r.approval_status = ?")
        params.append(target_status)
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
        SELECT r.record_id, r.version_id, r.record_type, r.canonical_path, r.canonical_line, r.record_sha256, r.validation_status, r.approval_status, r.created_at, v.document_id, d.title
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        LEFT JOIN documents d ON v.document_id = d.document_id
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
                "document_title": row[10] or row[9],
            }
        )

    conn.close()
    return ok_response({"items": items, "total": total, "page": page, "page_size": page_size})


@router.get("/records/{record_id:path}")
@router.get("/reviews/records/{record_id:path}")
def get_record_detail(record_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT r.record_id, r.version_id, r.record_type, r.canonical_path, r.canonical_line, r.record_sha256,
               r.validation_status, r.approval_status, r.created_at, v.document_id, d.title
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        LEFT JOIN documents d ON v.document_id = d.document_id
        WHERE r.record_id = ?
        """,
        (record_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        error_response("RECORD_NOT_FOUND", f"Record {record_id} not found", status_code=404)

    rec_data = {
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
        "document_title": row[10] or row[9],
    }

    # Read canonical line preview (up to 20,000 chars)
    settings = load_settings()
    c_abs_path = settings.data_root_path / str(rec_data["canonical_path"])
    text_preview = None
    if c_abs_path.exists():
        target_line = int(rec_data["canonical_line"])
        with open(c_abs_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                if idx == target_line:
                    try:
                        parsed = json.loads(line)
                        text_preview = parsed.get("text") or parsed.get("title") or line[:20000]
                    except Exception:
                        text_preview = line[:20000]
                    break

    blockers = list_open_blocking_issues(conn, subject_id=record_id)
    conn.close()

    rec_data["text_preview"] = text_preview
    rec_data["open_blockers"] = blockers
    return ok_response(rec_data)


# 8.7 Review
@router.post("/records/{record_id:path}/approve")
@router.post("/reviews/records/{record_id:path}/approve")
async def approve_record(record_id: str, req: ReviewRequest):
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            res = approve_record_with_checks(conn, record_id, req.reviewer, req.note)
            return ok_response(res)
        except BlockingValidationIssueExists as e:
            error_response(
                "BLOCKING_ISSUES_EXIST",
                "Bu kayıt henüz onaylanamaz. Çözülmesi gereken doğrulama sorunları bulunuyor.",
                status_code=400,
                details={"record_id": record_id, "error": str(e)},
            )
        except Exception as e:
            error_response("REVIEW_FAILED", str(e), status_code=400)
        finally:
            conn.close()


@router.post("/records/{record_id:path}/reject")
@router.post("/reviews/records/{record_id:path}/reject")
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
            res = approve_version_streaming(conn, version_id=version_id, reviewer=req.reviewer, note=req.note)
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
        where_clauses.append("v.status = ?")
        params.append(status)
    if severity:
        where_clauses.append("v.severity = ?")
        params.append(severity)
    if subject_type:
        where_clauses.append("v.subject_type = ?")
        params.append(subject_type)
    if subject_id:
        where_clauses.append("v.subject_id = ?")
        params.append(subject_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    c.execute(
        f"""SELECT v.issue_id, v.subject_type, v.subject_id, v.severity, v.code, v.message, v.status, v.opened_at,
                   COALESCE(
                       (SELECT d.title FROM documents d WHERE d.document_id = v.subject_id),
                       (SELECT d.title FROM documents d JOIN versions ver ON ver.document_id = d.document_id WHERE ver.version_id = v.subject_id),
                       (SELECT d.title FROM documents d JOIN versions ver ON ver.document_id = d.document_id JOIN records rec ON rec.version_id = ver.version_id WHERE rec.record_id = v.subject_id),
                       (SELECT d.title FROM documents d JOIN artifacts a ON a.document_id = d.document_id WHERE a.artifact_id = v.subject_id)
                   ) AS document_title,
                   COALESCE(
                       (CASE WHEN v.subject_type = 'document' THEN v.subject_id ELSE NULL END),
                       (SELECT ver.document_id FROM versions ver WHERE ver.version_id = v.subject_id),
                       (SELECT ver.document_id FROM versions ver JOIN records rec ON rec.version_id = ver.version_id WHERE rec.record_id = v.subject_id),
                       (SELECT a.document_id FROM artifacts a WHERE a.artifact_id = v.subject_id)
                   ) AS document_id,
                   (SELECT a.source_id FROM artifacts a WHERE a.artifact_id = v.subject_id) AS source_id,
                   (SELECT a.raw_path FROM artifacts a WHERE a.artifact_id = v.subject_id) AS raw_path
            FROM validation_issues v {where_sql} ORDER BY v.opened_at DESC""",
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
            "document_title": r[8],
            "document_id": r[9],
            "source_id": r[10],
            "raw_path": r[11],
        }
        for r in c.fetchall()
    ]
    conn.close()
    return ok_response(issues)


@router.post("/issues/{issue_id:path}/resolve")
async def resolve_issue_endpoint(issue_id: str, request: Request, req: Optional[IssueResolveRequest] = None):
    actor = extract_actor(request) if request else "web-user"
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            status = req.status if req else "resolved"
            resolved_by = req.resolved_by if req and req.resolved_by else actor
            note = req.resolution_note if req and req.resolution_note else "Manuel inceleme ile çözüldü kabul edildi."
            resolve_issue(conn, issue_id=issue_id, status=status, resolved_by=resolved_by, resolution_note=note)
            log_audit_event(
                conn,
                actor=resolved_by,
                action="issue_resolved",
                subject_type="issue",
                subject_id=issue_id,
                reason=note,
                details_json=json.dumps({"status": status, "resolution_note": note}),
            )
            return ok_response(
                {"issue_id": issue_id, "status": status, "resolved_by": resolved_by, "resolution_note": note}
            )
        finally:
            conn.close()


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
@router.post("/releases/build")
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
        try:
            from mesa_legal_data.release import ReleasePublishError, publish_release

            result = publish_release(release_id)
            return ok_response(result)
        except ReleasePublishError as e:
            msg = str(e)
            if "not found" in msg.lower():
                error_response("RELEASE_NOT_FOUND", msg, status_code=404)
            else:
                error_response("INVALID_STATE", msg, status_code=409)
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            error_response("RELEASE_PUBLISH_FAILED", str(e), status_code=400)


@router.post("/releases/{release_id:path}/import")
@router.post("/releases/{release_id:path}/import-to-mesa")
@router.post("/releases/{release_id:path}/import-to-staging")
@router.post("/releases/{release_id:path}/import-staging")
async def import_release_endpoint(release_id: str):
    async with write_lock.acquire_write():
        try:
            res = import_release_to_staging(release_id)
            return ok_response(res)
        except ReleaseNotFound as e:
            error_response("RELEASE_NOT_FOUND", str(e), status_code=404)
        except (ReleaseNotPublished, ReleaseRevoked, ReleaseStateChanged) as e:
            error_response("RELEASE_NOT_PUBLISHED", str(e), status_code=409)
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
@router.post("/admin/backup")
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


# --- EXPORTS & PACKAGES ---


@router.get("/exports")
def list_exports_endpoint(limit: int = Query(50, ge=1, le=200)):
    from mesa_legal_data.catalog import list_export_packages

    conn = get_connection()
    items = list_export_packages(conn, limit=limit)
    conn.close()
    return ok_response(items)


@router.post("/exports")
async def create_export_endpoint(request: Request):
    from mesa_legal_data.exports import generate_export_package

    actor = extract_actor(request)
    body = await request.json()
    export_type = body.get("export_type", "records_jsonl")
    filters = body.get("filters", {})
    export_id = f"exp-{uuid.uuid4().hex[:12]}"

    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            res = generate_export_package(
                conn,
                export_id=export_id,
                export_type=export_type,
                filters=filters,
                actor=actor,
            )
            return ok_response(res)
        except ValueError as e:
            error_response("EXPORT_TYPE_NOT_SUPPORTED", str(e), status_code=400)
        finally:
            conn.close()


@router.get("/exports/{export_id}")
def get_export_endpoint(export_id: str):

    conn = get_connection()
    exp = get_export_package(conn, export_id)
    conn.close()
    if not exp:
        error_response("NOT_FOUND", f"Export {export_id} not found", status_code=404)
    return ok_response(exp)


@router.get("/exports/{export_id}/download")
def download_export_endpoint(export_id: str, request: Request):
    from fastapi.responses import FileResponse

    actor = extract_actor(request)
    conn = get_connection()
    exp = get_export_package(conn, export_id)
    if not exp:
        conn.close()
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Export {export_id} not found"})

    data_root = load_settings().data_root_path
    safe_path = validate_file_download(data_root, exp["relative_path"], expected_sha256=exp.get("sha256"))

    log_audit_event(
        conn,
        actor=actor,
        action="download_export",
        subject_type="export",
        subject_id=export_id,
        new_sha256=exp.get("sha256"),
    )
    conn.close()

    safe_filename = Path(exp["relative_path"]).name
    return FileResponse(
        path=str(safe_path),
        media_type="application/octet-stream",
        filename=safe_filename,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


# --- OPERATIONS JOBS ---


@router.post("/operations/jobs")
async def create_operation_job_endpoint(request: Request):
    from mesa_legal_data.operations import submit_operation

    actor = extract_actor(request)
    body = await request.json()
    op_type = body.get("operation_type", "bulk_review")
    input_dict = body.get("input", {})

    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            op_id = submit_operation(
                conn,
                operation_type=op_type,
                requested_by=actor,
                input_dict=input_dict,
            )
            return ok_response({"operation_id": op_id, "status": "submitted"})
        except ValueError as e:
            error_response("OPERATION_TYPE_NOT_SUPPORTED", str(e), status_code=400)
        finally:
            conn.close()


@router.post("/operations/jobs/{operation_id}/cancel")
async def cancel_operation_job_endpoint(operation_id: str, request: Request):
    from mesa_legal_data.operations import cancel_operation

    actor = extract_actor(request)
    async with write_lock.acquire_write():
        conn = get_connection()
        try:
            cancel_operation(conn, operation_id, actor=actor)
            return ok_response({"operation_id": operation_id, "status": "cancelled"})
        finally:
            conn.close()


@router.get("/operations/jobs")
def list_operations_jobs_endpoint():
    from mesa_legal_data.catalog import list_operation_jobs

    conn = get_connection()
    jobs = list_operation_jobs(conn)
    conn.close()
    return ok_response(jobs)


@router.get("/operations/jobs/{operation_id}")
def get_operation_job_endpoint(operation_id: str):
    from mesa_legal_data.catalog import get_operation_job

    conn = get_connection()
    job = get_operation_job(conn, operation_id)
    conn.close()
    if not job:
        error_response("NOT_FOUND", f"Operation job {operation_id} not found", status_code=404)
    return ok_response(job)


# --- AUDIT EVENTS ---


@router.get("/audit-events")
def list_audit_events_endpoint(
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    from mesa_legal_data.catalog import list_audit_events

    conn = get_connection()
    evts = list_audit_events(
        conn,
        subject_type=subject_type,
        subject_id=subject_id,
        action=action,
        actor=actor,
        limit=limit,
        offset=offset,
    )
    conn.close()
    return ok_response(evts)


@router.get("/releases/{release_id:path}/package")
def release_package_endpoint(release_id: str, request: Request):
    import tarfile

    from fastapi.responses import FileResponse

    from mesa_legal_data.catalog import get_release

    actor = extract_actor(request)
    conn = get_connection()
    rel = get_release(conn, release_id)
    if not rel:
        conn.close()
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Release {release_id} not found"})

    data_root = load_settings().data_root_path
    rel_dir = data_root / rel["release_path"]
    if not rel_dir.exists():
        conn.close()
        raise HTTPException(
            status_code=404, detail={"code": "RELEASE_DIR_NOT_FOUND", "message": "Release directory missing"}
        )

    pkg_tar = data_root / "exports" / f"release_package_{Path(release_id).name}.tar.gz"
    pkg_tar.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(pkg_tar, "w:gz") as tar:
        tar.add(rel_dir, arcname=Path(release_id).name)

    log_audit_event(
        conn,
        actor=actor,
        action="download_release_package",
        subject_type="release",
        subject_id=release_id,
    )
    conn.close()

    safe_filename = pkg_tar.name
    return FileResponse(
        path=str(pkg_tar),
        media_type="application/gzip",
        filename=safe_filename,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


# --- DATA EXPLORER API ---


@router.get("/explorer/search")
@router.get("/explorer/records")
def explorer_search_endpoint(
    q: Optional[str] = Query(None),
    record_type: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    source_id: Optional[str] = Query(None),
    approval_status: Optional[str] = Query(None),
    approval: Optional[str] = Query(None),
    validation_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None),
    offset: Optional[int] = Query(None),
    sort: Optional[str] = Query(None),
):
    conn = get_connection()
    c = conn.cursor()

    effective_record_type = record_type or type
    effective_approval = approval_status or approval
    effective_page_size = limit if (limit is not None and limit > 0) else page_size
    if offset is not None and effective_page_size > 0:
        effective_page = (offset // effective_page_size) + 1
    else:
        effective_page = page

    where_clauses = ["1=1"]
    params: list[Any] = []

    if q:
        where_clauses.append("(r.record_id LIKE ? OR r.record_type LIKE ? OR d.title LIKE ?)")
        term = f"%{q}%"
        params.extend([term, term, term])

    if effective_record_type:
        where_clauses.append("r.record_type = ?")
        params.append(effective_record_type)

    if source_id:
        where_clauses.append("a.source_id = ?")
        params.append(source_id)

    if effective_approval:
        where_clauses.append("r.approval_status = ?")
        params.append(effective_approval)

    if validation_status:
        where_clauses.append("r.validation_status = ?")
        params.append(validation_status)

    where_str = " AND ".join(where_clauses)

    count_sql = f"""
        SELECT COUNT(*)
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        JOIN artifacts a ON v.artifact_id = a.artifact_id
        JOIN documents d ON v.document_id = d.document_id
        WHERE {where_str}
    """
    c.execute(count_sql, params)
    total = c.fetchone()[0]

    order_clause = "r.created_at DESC"
    if sort == "record_id":
        order_clause = "r.record_id ASC"
    elif sort == "record_type":
        order_clause = "r.record_type ASC"
    elif sort == "created_at":
        order_clause = "r.created_at DESC"

    offset = (effective_page - 1) * effective_page_size
    data_sql = f"""
        SELECT r.record_id, r.record_type, r.version_id, r.approval_status, r.validation_status, r.canonical_path, r.canonical_line, r.record_sha256, d.document_id, d.title, a.source_id, r.created_at
        FROM records r
        JOIN versions v ON r.version_id = v.version_id
        JOIN artifacts a ON v.artifact_id = a.artifact_id
        JOIN documents d ON v.document_id = d.document_id
        WHERE {where_str}
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
    """
    c.execute(data_sql, params + [effective_page_size, offset])
    rows = c.fetchall()
    conn.close()

    items = [
        {
            "record_id": row[0],
            "record_type": row[1],
            "version_id": row[2],
            "approval_status": row[3],
            "validation_status": row[4],
            "canonical_path": row[5],
            "canonical_line": row[6],
            "record_sha256": row[7],
            "document_id": row[8],
            "title": row[9],
            "source_id": row[10],
            "created_at": row[11],
        }
        for row in rows
    ]

    return ok_response(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/explorer/facets")
def explorer_facets_endpoint():
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT record_type, COUNT(*) FROM records GROUP BY record_type")
    record_types = {r[0]: r[1] for r in c.fetchall()}

    c.execute(
        "SELECT a.source_id, COUNT(*) FROM records r JOIN versions v ON r.version_id = v.version_id JOIN artifacts a ON v.artifact_id = a.artifact_id GROUP BY a.source_id"
    )
    sources = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT approval_status, COUNT(*) FROM records GROUP BY approval_status")
    approval_statuses = {r[0]: r[1] for r in c.fetchall()}

    c.execute("SELECT validation_status, COUNT(*) FROM records GROUP BY validation_status")
    validation_statuses = {r[0]: r[1] for r in c.fetchall()}

    conn.close()

    return ok_response(
        {
            "record_types": record_types,
            "sources": sources,
            "approval_statuses": approval_statuses,
            "validation_statuses": validation_statuses,
        }
    )
