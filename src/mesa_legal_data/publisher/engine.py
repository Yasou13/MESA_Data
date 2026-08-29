import hashlib
import json
import time
import uuid
from typing import Any, Callable

from mesa_legal_data.catalog import get_connection
from mesa_legal_data.config import load_settings
from mesa_legal_data.publisher.chunker import plan_source_chunks
from mesa_legal_data.publisher.client import MesaClient, MesaClientError
from mesa_legal_data.publisher.hashing import generate_idempotency_key
from mesa_legal_data.publisher.ledger import (
    create_delivery,
    get_delivery,
    get_mesa_target_settings,
    insert_delivery_item,
    is_chunk_already_committed,
    list_failed_delivery_items,
    update_delivery_item_state,
    update_delivery_progress,
)
from mesa_legal_data.publisher.models import (
    DeliveryPlanSummary,
    DeliveryStatus,
    MutationState,
    SourceChunk,
)


def get_ready_versions_and_content(conn) -> tuple[list[dict[str, Any]], int]:
    """
    Fetches approved versions ready for publishing, and count of blocked versions.
    """
    cursor = conn.cursor()
    # Only the true current version can make a document publishable.  Historical
    # blocked or approved versions must not affect another current document.
    cursor.execute(
        """SELECT count(*) FROM documents d JOIN versions v ON v.version_id = d.current_version_id
           WHERE v.quality_status = 'BLOCK'"""
    )
    blocked_count = cursor.fetchone()[0]

    # 2. Fetch approved versions
    cursor.execute("""SELECT v.version_id, v.document_id, v.canonical_path, v.canonical_sha256,
                             v.revision_number, d.family
                      FROM documents d
                      JOIN versions v ON v.version_id = d.current_version_id
                      WHERE v.approval_status = 'approved'
                        AND v.validation_status = 'valid'
                        AND v.privacy_status IN ('clean', 'approved')
                        AND v.quality_status = 'PASS'
                      ORDER BY v.created_at ASC""")
    rows = cursor.fetchall()
    version_items = [
        {
            "version_id": r[0],
            "document_id": r[1],
            "canonical_path": r[2],
            "canonical_sha256": r[3],
            "revision_number": r[4],
            "family": r[5],
        }
        for r in rows
    ]
    return version_items, blocked_count


def build_delivery_plan(
    target_key: str = "default",
) -> tuple[list[tuple[SourceChunk, bool]], DeliveryPlanSummary]:
    """
    Constructs the delivery plan across all ready versions.
    Returns:
      - List of (SourceChunk, is_already_committed)
      - DeliveryPlanSummary
    """
    conn = get_connection()
    target_settings = get_mesa_target_settings(conn, target_key)
    versions, blocked_count = get_ready_versions_and_content(conn)
    data_root = load_settings().data_root_path

    all_chunks: list[tuple[SourceChunk, bool]] = []
    unique_docs = set()
    total_bytes = 0
    already_committed = 0
    unreadable_versions = 0

    for v_info in versions:
        doc_id = v_info["document_id"]
        v_id = v_info["version_id"]
        canonical_text = ""
        records: list[dict[str, Any]] = []
        c_cur = conn.cursor()
        c_cur.execute(
            """SELECT record_id, record_type, canonical_path, canonical_line, record_sha256
               FROM records
               WHERE version_id = ? AND validation_status = 'valid' AND approval_status = 'approved'
               ORDER BY canonical_path, canonical_line""",
            (v_id,),
        )
        rec_rows = c_cur.fetchall()

        try:
            lines_by_path: dict[str, list[str]] = {}
            for record_id, record_type, rel_path, line_number, expected_hash in rec_rows:
                if rel_path not in lines_by_path:
                    abs_path = data_root / rel_path
                    lines_by_path[rel_path] = abs_path.read_text(encoding="utf-8").splitlines(keepends=True)
                lines = lines_by_path[rel_path]
                if line_number < 1 or line_number > len(lines):
                    raise ValueError(f"Canonical line out of bounds for {record_id}")
                line = lines[line_number - 1]
                if hashlib.sha256(line.encode("utf-8")).hexdigest() != expected_hash:
                    raise ValueError(f"Canonical hash mismatch for {record_id}")
                item = json.loads(line)
                if item.get("id") != record_id or item.get("record_type") != record_type:
                    raise ValueError(f"Canonical identity mismatch for {record_id}")

                if record_type == "legislation":
                    canonical_text = item.get("full_text") or ""
                elif record_type == "decision":
                    canonical_text = item.get("text") or ""
                elif record_type == "article":
                    span = item.get("source_span") or {}
                    records.append(
                        {
                            "record_id": record_id,
                            "record_type": "article",
                            "char_start": span.get("char_start"),
                            "char_end": span.get("char_end"),
                            "ordinal": item.get("ordinal", line_number),
                            "title": item.get("heading"),
                            "article_number": item.get("article_number"),
                            "content": item.get("text") or "",
                        }
                    )
            if not canonical_text.strip():
                raise ValueError(f"Version {v_id} has no authoritative canonical document text")
        except (OSError, ValueError, json.JSONDecodeError):
            unreadable_versions += 1
            continue

        unique_docs.add(doc_id)

        chunks = plan_source_chunks(
            document_id=doc_id,
            version_id=v_id,
            canonical_text=canonical_text,
            records=records,
            content_limit_chars=target_settings.content_limit_chars,
        )

        for chunk in chunks:
            total_bytes += len(chunk.content.encode("utf-8"))
            is_committed = is_chunk_already_committed(
                conn,
                target_key=target_key,
                document_id=doc_id,
                version_id=v_id,
                chunk_id=chunk.chunk_id,
                content_hash=chunk.content_hash,
            )
            if is_committed:
                already_committed += 1
            all_chunks.append((chunk, is_committed))

    conn.close()

    summary = DeliveryPlanSummary(
        ready_documents=len(unique_docs),
        ready_versions=len(versions) - unreadable_versions,
        estimated_chunks=len(all_chunks),
        total_canonical_bytes=total_bytes,
        already_committed_chunks=already_committed,
        new_chunks_to_send=len(all_chunks) - already_committed,
        blocked_versions_excluded=blocked_count,
        unreadable_versions_excluded=unreadable_versions,
    )
    return all_chunks, summary


def execute_publish_delivery(
    *,
    delivery_id: str | None = None,
    release_id: str | None = None,
    target_key: str = "default",
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Executes an end-to-end MESA v4 publish delivery:
      1. Initializes client with target settings.
      2. Runs preflight checks (aborts if FAIL).
      3. Builds chunk plan and registers delivery ledger.
      4. Iterates through chunks with cross-release dedup and idempotency keys.
      5. Polls mutations until COMMITTED or terminal failure.
      6. Writes truthful status to ledger.
    """
    conn = get_connection()
    target_settings = get_mesa_target_settings(conn, target_key)
    client = MesaClient(settings=target_settings)

    if not delivery_id:
        delivery_id = f"del-{uuid.uuid4().hex[:12]}"

    # 1. Build delivery plan
    chunk_tuples, summary = build_delivery_plan(target_key=target_key)
    total_items = len(chunk_tuples)

    preflight = client.run_preflight_checks(
        ready_documents_count=summary.ready_documents,
        ready_versions_count=summary.ready_versions,
        estimated_chunks_count=summary.estimated_chunks,
        total_canonical_bytes=summary.total_canonical_bytes,
        blocked_versions_count=summary.blocked_versions_excluded,
        unreadable_versions_count=summary.unreadable_versions_excluded,
    )
    if preflight.overall_status == "FAIL":
        conn.close()
        failures = "; ".join(check.message for check in preflight.checks if check.status == "FAIL")
        raise MesaClientError(f"Publisher preflight failed: {failures}")

    # 2. Create delivery in ledger
    create_delivery(
        conn,
        delivery_id=delivery_id,
        release_id=release_id,
        target_key=target_key,
        total_items=total_items,
    )

    update_delivery_progress(
        conn,
        delivery_id=delivery_id,
        status=DeliveryStatus.SENDING.value,
        committed_items=0,
        failed_items=0,
        skipped_items=0,
    )

    committed_count = 0
    failed_count = 0
    skipped_count = 0
    last_err = None

    for idx, (chunk, is_already_done) in enumerate(chunk_tuples, start=1):
        item_id = f"item-{uuid.uuid4().hex[:12]}"
        idemp_key = generate_idempotency_key(
            tenant_id=target_settings.tenant_id,
            workspace_id=target_settings.workspace_id,
            dataset_id=target_settings.dataset_id,
            document_id=chunk.document_id,
            version_id=chunk.version_id,
            chunk_id=chunk.chunk_id,
            content_hash=chunk.content_hash,
        )

        payload_json = json.dumps(chunk.model_dump(), sort_keys=True)

        if is_already_done:
            # Cross-release dedup: skip without sending HTTP mutation
            insert_delivery_item(
                conn,
                item_id=item_id,
                delivery_id=delivery_id,
                document_id=chunk.document_id,
                version_id=chunk.version_id,
                chunk_id=chunk.chunk_id,
                content_hash=chunk.content_hash,
                idempotency_key=idemp_key,
                remote_state=MutationState.SKIPPED.value,
                payload_json=payload_json,
            )
            skipped_count += 1
        else:
            insert_delivery_item(
                conn,
                item_id=item_id,
                delivery_id=delivery_id,
                document_id=chunk.document_id,
                version_id=chunk.version_id,
                chunk_id=chunk.chunk_id,
                content_hash=chunk.content_hash,
                idempotency_key=idemp_key,
                remote_state=MutationState.SENDING.value,
                payload_json=payload_json,
            )

            # Submit chunk to MESA v4
            pub_res = client.publish_source_chunk(chunk, idempotency_key=idemp_key)
            remote_mutation_id = pub_res.get("mutation_id")
            initial_state = pub_res.get("state", MutationState.FAILED.value)

            final_item_state = initial_state
            if initial_state in (MutationState.QUEUED.value, MutationState.PROCESSING.value):
                # Poll mutation until terminal state
                update_delivery_item_state(
                    conn,
                    item_id=item_id,
                    remote_state=MutationState.PROCESSING.value,
                    remote_mutation_id=remote_mutation_id,
                )
                poll_attempts = 0
                while poll_attempts < 5:
                    time.sleep(0.5)
                    poll_res = client.get_mutation_status(remote_mutation_id or "")
                    polled_state = poll_res.get("state")
                    if polled_state in (
                        MutationState.COMMITTED.value,
                        MutationState.FAILED.value,
                        MutationState.REJECTED.value,
                    ):
                        final_item_state = polled_state
                        break
                    poll_attempts += 1
                if final_item_state in (MutationState.QUEUED.value, MutationState.PROCESSING.value):
                    final_item_state = MutationState.AWAITING_MUTATION.value

            if final_item_state == MutationState.COMMITTED.value:
                committed_count += 1
                update_delivery_item_state(
                    conn,
                    item_id=item_id,
                    remote_state=MutationState.COMMITTED.value,
                    remote_mutation_id=remote_mutation_id,
                )
            elif final_item_state == MutationState.REJECTED.value:
                failed_count += 1
                last_err = pub_res.get("message") or "Semantic rejection by MESA"
                update_delivery_item_state(
                    conn,
                    item_id=item_id,
                    remote_state=MutationState.REJECTED.value,
                    remote_mutation_id=remote_mutation_id,
                    last_error=last_err,
                )
            elif final_item_state == MutationState.AWAITING_MUTATION.value:
                update_delivery_item_state(
                    conn,
                    item_id=item_id,
                    remote_state=MutationState.AWAITING_MUTATION.value,
                    remote_mutation_id=remote_mutation_id,
                    last_error="Local poll window elapsed; remote mutation is still pending",
                )
            else:
                failed_count += 1
                last_err = pub_res.get("message") or "Mutation failed to commit"
                update_delivery_item_state(
                    conn,
                    item_id=item_id,
                    remote_state=MutationState.FAILED.value,
                    remote_mutation_id=remote_mutation_id,
                    last_error=last_err,
                )

        if progress_callback:
            progress_callback(
                {
                    "delivery_id": delivery_id,
                    "processed": idx,
                    "total": total_items,
                    "committed": committed_count,
                    "failed": failed_count,
                    "skipped": skipped_count,
                }
            )

    # 3. Compute final delivery status
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM mesa_delivery_items WHERE delivery_id = ? AND remote_state = 'AWAITING_MUTATION'", (delivery_id,))
    awaiting_count = cursor.fetchone()[0]
    if awaiting_count:
        final_delivery_status = DeliveryStatus.AWAITING_MUTATION.value
    elif total_items == 0:
        final_delivery_status = DeliveryStatus.COMMITTED.value
    elif failed_count == 0:
        final_delivery_status = DeliveryStatus.COMMITTED.value
    elif committed_count > 0 or skipped_count > 0:
        final_delivery_status = DeliveryStatus.PARTIAL.value
    else:
        final_delivery_status = DeliveryStatus.FAILED.value

    update_delivery_progress(
        conn,
        delivery_id=delivery_id,
        status=final_delivery_status,
        committed_items=committed_count,
        failed_items=failed_count,
        skipped_items=skipped_count,
        last_error=last_err,
        finished=final_delivery_status != DeliveryStatus.AWAITING_MUTATION.value,
    )
    conn.close()

    return {
        "delivery_id": delivery_id,
        "status": final_delivery_status,
        "total_items": total_items,
        "committed_items": committed_count,
        "failed_items": failed_count,
        "skipped_items": skipped_count,
        "last_error": last_err,
    }


def retry_delivery_failures(
    delivery_id: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Retries only the failed/timed out items of a delivery using the same idempotency keys.
    """
    conn = get_connection()
    delivery = get_delivery(conn, delivery_id)
    if not delivery:
        conn.close()
        raise ValueError(f"Delivery {delivery_id} not found")

    target_settings = get_mesa_target_settings(conn, delivery.get("target_key", "default"))
    client = MesaClient(settings=target_settings)

    failed_items = list_failed_delivery_items(conn, delivery_id)
    if not failed_items:
        conn.close()
        return {"delivery_id": delivery_id, "retried_count": 0, "message": "No failed items eligible for retry"}

    retried_success = 0
    retried_failed = 0
    last_err = None

    for idx, item in enumerate(failed_items, start=1):
        item_id = item["item_id"]
        idemp_key = item["idempotency_key"]
        payload = item["payload"]
        chunk = SourceChunk(**payload)

        update_delivery_item_state(
            conn,
            item_id=item_id,
            remote_state=MutationState.SENDING.value,
        )

        remote_mutation_id = item.get("remote_mutation_id")
        if item.get("remote_state") == MutationState.AWAITING_MUTATION.value and remote_mutation_id:
            pub_res = client.get_mutation_status(remote_mutation_id)
            final_state = pub_res.get("state", MutationState.FAILED.value)
        else:
            pub_res = client.publish_source_chunk(chunk, idempotency_key=idemp_key)
            remote_mutation_id = pub_res.get("mutation_id")
            final_state = pub_res.get("state", MutationState.FAILED.value)

        if final_state in (MutationState.QUEUED.value, MutationState.PROCESSING.value):
            update_delivery_item_state(
                conn,
                item_id=item_id,
                remote_state=MutationState.PROCESSING.value,
                remote_mutation_id=remote_mutation_id,
            )
            for _ in range(5):
                time.sleep(0.5)
                poll_res = client.get_mutation_status(remote_mutation_id or "")
                polled_state = poll_res.get("state", MutationState.FAILED.value)
                if polled_state in (
                    MutationState.COMMITTED.value,
                    MutationState.FAILED.value,
                    MutationState.REJECTED.value,
                ):
                    final_state = polled_state
                    if polled_state != MutationState.COMMITTED.value:
                        last_err = poll_res.get("error") or last_err
                    break
            if final_state in (MutationState.QUEUED.value, MutationState.PROCESSING.value):
                final_state = MutationState.AWAITING_MUTATION.value

        if final_state == MutationState.COMMITTED.value:
            retried_success += 1
            update_delivery_item_state(
                conn,
                item_id=item_id,
                remote_state=MutationState.COMMITTED.value,
                remote_mutation_id=remote_mutation_id,
            )
        elif final_state == MutationState.AWAITING_MUTATION.value:
            update_delivery_item_state(
                conn,
                item_id=item_id,
                remote_state=MutationState.AWAITING_MUTATION.value,
                remote_mutation_id=remote_mutation_id,
                last_error="Local poll window elapsed; remote mutation is still pending",
            )
        else:
            retried_failed += 1
            last_err = pub_res.get("message")
            update_delivery_item_state(
                conn,
                item_id=item_id,
                remote_state=MutationState.FAILED.value,
                remote_mutation_id=remote_mutation_id,
                last_error=last_err,
            )

        if progress_callback:
            progress_callback(
                {
                    "delivery_id": delivery_id,
                    "retried_processed": idx,
                    "retried_total": len(failed_items),
                    "retried_success": retried_success,
                    "retried_failed": retried_failed,
                }
            )

    # Re-calculate overall delivery totals
    c = conn.cursor()
    c.execute(
        """SELECT remote_state, count(*) FROM mesa_delivery_items WHERE delivery_id = ? GROUP BY remote_state""",
        (delivery_id,),
    )
    counts = dict(c.fetchall())
    committed = counts.get("COMMITTED", 0)
    failed = counts.get("FAILED", 0) + counts.get("REJECTED", 0)
    skipped = counts.get("SKIPPED", 0)

    awaiting = counts.get("AWAITING_MUTATION", 0)
    if awaiting:
        new_status = DeliveryStatus.AWAITING_MUTATION.value
    elif failed == 0:
        new_status = DeliveryStatus.COMMITTED.value
    elif committed > 0 or skipped > 0:
        new_status = DeliveryStatus.PARTIAL.value
    else:
        new_status = DeliveryStatus.FAILED.value

    update_delivery_progress(
        conn,
        delivery_id=delivery_id,
        status=new_status,
        committed_items=committed,
        failed_items=failed,
        skipped_items=skipped,
        last_error=last_err,
        finished=new_status != DeliveryStatus.AWAITING_MUTATION.value,
    )
    conn.close()

    return {
        "delivery_id": delivery_id,
        "status": new_status,
        "retried_count": len(failed_items),
        "retried_success": retried_success,
        "retried_failed": retried_failed,
        "last_error": last_err,
    }
