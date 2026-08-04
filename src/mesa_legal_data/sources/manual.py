import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from mesa_legal_data.catalog import (
    create_run,
    finish_run,
    get_connection,
    insert_artifact,
    upsert_document,
)
from mesa_legal_data.config import load_settings
from mesa_legal_data.content_types import validate_file_content
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.models import FetchedArtifact
from mesa_legal_data.storage import atomic_write
from mesa_legal_data.storage_paths import build_raw_path, secure_slug


def import_manual_file(
    file_path: Path,
    source_id: str,
    document_id: str,
    family: str = "legislation",
    document_type: str = "law",
    jurisdiction: str = "TR",
    title: str | None = None,
    stable_key: str | None = None,
) -> FetchedArtifact:
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    settings = load_settings()
    data_root = settings.data_root_path

    # 1. Content & MIME validation
    allowed_mimes = ["application/pdf", "text/html", "text/plain", "application/xml"]
    detected_mime = validate_file_content(
        str(file_path),
        allowed_mimes=allowed_mimes,
        max_bytes=100 * 1024 * 1024,  # 100 MB limit
    )

    # 2. Hash calculation
    with open(file_path, "rb") as f:
        artifact_sha256 = hash_stream(f)

    # 3. Path construction
    ext = file_path.suffix if file_path.suffix else ".bin"
    doc_key = stable_key if stable_key else secure_slug(document_id)
    year = datetime.now(UTC).year

    rel_path = build_raw_path(
        family=family,
        source=source_id,
        year=year,
        document_key=doc_key,
        artifact_sha256=artifact_sha256,
        ext=ext,
    )
    full_target_payload = data_root / rel_path

    # 4. Storage (atomic write)
    with open(file_path, "rb") as f:
        atomic_write(f, full_target_payload)

    # 5. Metadata json
    retrieved_at = datetime.now(UTC).isoformat()
    byte_size = os.path.getsize(file_path)
    artifact_id = f"sha256:{artifact_sha256}"

    meta_dict = {
        "artifact_id": artifact_id,
        "document_key": doc_key,
        "source_id": source_id,
        "source_url": f"file://{file_path.resolve()}",
        "retrieved_at": retrieved_at,
        "fetch_method": "manual",
        "http_status": 200,
        "declared_content_type": detected_mime,
        "detected_content_type": detected_mime,
        "byte_size": byte_size,
        "sha256": artifact_sha256,
        "etag": None,
        "last_modified": None,
        "collector_version": "1.0.0",
        "access_policy_version": "1.0.0",
    }

    metadata_path = full_target_payload.parent / "metadata.json"
    with open(file_path, "rb") as f:
        # Atomic write for metadata as well
        import io

        meta_bytes = json.dumps(meta_dict, indent=2).encode("utf-8")
        atomic_write(io.BytesIO(meta_bytes), metadata_path)

    # 6. Database record
    conn = get_connection()
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    # Ensure run is tracked
    create_run(
        conn=conn,
        run_id=run_id,
        command=f"collect manual --source {source_id} --file {file_path}",
        source_id=source_id,
        code_version="1.0.0",
        config_sha256="manual",
        input_json=json.dumps({"file": str(file_path), "document_id": document_id}),
    )

    # Upsert document
    actual_stable_key = doc_key
    upsert_document(
        conn=conn,
        document_id=document_id,
        family=family,
        document_type=document_type,
        jurisdiction=jurisdiction,
        title=title,
        stable_key=actual_stable_key,
        lifecycle_status="fetched",
    )

    # Insert artifact
    insert_artifact(
        conn=conn,
        artifact_id=artifact_id,
        document_id=document_id,
        source_id=source_id,
        source_url=f"file://{file_path.resolve()}",
        retrieved_at=retrieved_at,
        fetch_method="manual",
        http_status=200,
        declared_content_type=detected_mime,
        detected_content_type=detected_mime,
        byte_size=byte_size,
        sha256=artifact_sha256,
        raw_path=str(rel_path),
        etag=None,
        last_modified=None,
        transport_status="verified",
        error_code=None,
        metadata_json=json.dumps(meta_dict),
    )

    finish_run(
        conn=conn,
        run_id=run_id,
        status="succeeded",
        counters_json=json.dumps({"artifacts_collected": 1}),
    )
    conn.close()

    return FetchedArtifact(
        artifact_id=artifact_id,
        document_id=document_id,
        source_id=source_id,
        source_url=f"file://{file_path.resolve()}",
        retrieved_at=retrieved_at,
        fetch_method="manual",
        http_status=200,
        declared_content_type=detected_mime,
        detected_content_type=detected_mime,
        byte_size=byte_size,
        sha256=artifact_sha256,
        raw_path=str(rel_path),
        transport_status="verified",
        metadata=meta_dict,
    )


def import_manual_url(
    url: str,
    source_id: str,
    document_id: str,
    family: str = "legislation",
    document_type: str = "law",
    jurisdiction: str = "TR",
    title: str | None = None,
    stable_key: str | None = None,
    require_https: bool = True,
) -> FetchedArtifact:
    import io

    from mesa_legal_data.sources.url_fetcher import fetch_url_stream

    settings = load_settings()
    data_root = settings.data_root_path

    # 1. Fetch URL stream safely
    status_code, headers, stream_gen = fetch_url_stream(
        url=url,
        source_id=source_id,
        document_family=family,
        require_https=require_https,
    )
    declared_content_type = headers.get("content-type")

    # Save to temp file first to validate MIME and calculate hash
    tmp_dir = data_root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = tmp_dir / f"download_{uuid.uuid4().hex}.tmp"

    try:
        with open(temp_file, "wb") as f:
            f.writelines(stream_gen)

        # 2. Content & MIME validation
        allowed_mimes = [
            "application/pdf",
            "text/html",
            "text/plain",
            "application/xml",
        ]
        detected_mime = validate_file_content(
            str(temp_file),
            allowed_mimes=allowed_mimes,
            max_bytes=100 * 1024 * 1024,
        )

        # 3. Hash calculation
        with open(temp_file, "rb") as f:
            artifact_sha256 = hash_stream(f)

        # 4. Path construction
        # Determine extension from URL or detected MIME
        ext = ".html" if "html" in detected_mime else (".pdf" if "pdf" in detected_mime else ".bin")
        doc_key = stable_key if stable_key else secure_slug(document_id)
        year = datetime.now(UTC).year

        rel_path = build_raw_path(
            family=family,
            source=source_id,
            year=year,
            document_key=doc_key,
            artifact_sha256=artifact_sha256,
            ext=ext,
        )
        full_target_payload = data_root / rel_path

        # 5. Storage (atomic write)
        with open(temp_file, "rb") as f:
            atomic_write(f, full_target_payload)

        # 6. Metadata json
        retrieved_at = datetime.now(UTC).isoformat()
        byte_size = os.path.getsize(temp_file)
        artifact_id = f"sha256:{artifact_sha256}"

        meta_dict = {
            "artifact_id": artifact_id,
            "document_key": doc_key,
            "source_id": source_id,
            "source_url": url,
            "retrieved_at": retrieved_at,
            "fetch_method": "manual_url",
            "http_status": status_code,
            "declared_content_type": declared_content_type,
            "detected_content_type": detected_mime,
            "byte_size": byte_size,
            "sha256": artifact_sha256,
            "etag": headers.get("etag"),
            "last_modified": headers.get("last-modified"),
            "collector_version": "1.0.0",
            "access_policy_version": "1.0.0",
        }

        metadata_path = full_target_payload.parent / "metadata.json"
        meta_bytes = json.dumps(meta_dict, indent=2).encode("utf-8")
        atomic_write(io.BytesIO(meta_bytes), metadata_path)

        # 7. Database record
        conn = get_connection()
        run_id = f"run-{uuid.uuid4().hex[:8]}"

        create_run(
            conn=conn,
            run_id=run_id,
            command=f"collect url --source {source_id} --url {url}",
            source_id=source_id,
            code_version="1.0.0",
            config_sha256="manual_url",
            input_json=json.dumps({"url": url, "document_id": document_id}),
        )

        upsert_document(
            conn=conn,
            document_id=document_id,
            family=family,
            document_type=document_type,
            jurisdiction=jurisdiction,
            title=title,
            stable_key=doc_key,
            lifecycle_status="fetched",
        )

        insert_artifact(
            conn=conn,
            artifact_id=artifact_id,
            document_id=document_id,
            source_id=source_id,
            source_url=url,
            retrieved_at=retrieved_at,
            fetch_method="manual_url",
            http_status=status_code,
            declared_content_type=declared_content_type,
            detected_content_type=detected_mime,
            byte_size=byte_size,
            sha256=artifact_sha256,
            raw_path=str(rel_path),
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            transport_status="verified",
            error_code=None,
            metadata_json=json.dumps(meta_dict),
        )

        finish_run(
            conn=conn,
            run_id=run_id,
            status="succeeded",
            counters_json=json.dumps({"artifacts_collected": 1}),
        )
        conn.close()

        return FetchedArtifact(
            artifact_id=artifact_id,
            document_id=document_id,
            source_id=source_id,
            source_url=url,
            retrieved_at=retrieved_at,
            fetch_method="manual_url",
            http_status=status_code,
            declared_content_type=declared_content_type,
            detected_content_type=detected_mime,
            byte_size=byte_size,
            sha256=artifact_sha256,
            raw_path=str(rel_path),
            transport_status="verified",
            metadata=meta_dict,
        )

    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
