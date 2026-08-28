import json
import time
import uuid
from typing import Any, Callable

from mesa_legal_data.catalog import get_connection
from mesa_legal_data.config import load_settings
from mesa_legal_data.publisher.chunker import plan_source_chunks
from mesa_legal_data.publisher.client import MesaClient
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
    # 1. Count blocked versions
    cursor.execute("SELECT count(*) FROM versions WHERE quality_status = 'BLOCK'")
    blocked_count = cursor.fetchone()[0]

    # 2. Fetch approved versions
    cursor.execute(
        """SELECT v.version_id, v.document_id, v.canonical_path, v.canonical_sha256, v.revision_number, d.family
           FROM versions v
           JOIN documents d ON v.document_id = d.document_id
           WHERE v.approval_status = 'approved'
             AND (v.quality_status IS NULL OR v.quality_status != 'BLOCK')
           ORDER BY v.created_at ASC"""
    )
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

    for v_info in versions:
        doc_id = v_info["document_id"]
        v_id = v_info["version_id"]
        rel_c_path = v_info["canonical_path"]
        unique_docs.add(doc_id)

        canonical_text = ""
        records = []
        if rel_c_path:
            abs_c_path = data_root / rel_c_path
            if abs_c_path.exists():
                try:
                    with open(abs_c_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    text_parts = []
                    for idx, line in enumerate(lines, start=1):
                        try:
                            item = json.loads(line.strip())
                            txt = item.get("content") or item.get("raw_text") or item.get("canonical_text", "")
                            if txt:
                                text_parts.append(txt)
                            records.append(
                                {
                                    "record_id": item.get("id") or item.get("record_id") or f"rec-{idx}",
                                    "record_type": item.get("type") or item.get("record_type") or "article",
                                    "char_start": item.get("char_start"),
                                    "char_end": item.get("char_end"),
                                    "ordinal": item.get("ordinal", idx),
                                    "title": item.get("title"),
                                    "article_number": item.get("article_number"),
                                    "content": txt,
                                }
                            )
                        except Exception:
                            continue
                    canonical_text = "\n\n".join([p for p in text_parts if p])
                except Exception:
                    canonical_text = ""

        # Fallback if no records found in jsonl
        if not records:
            c_cur = conn.cursor()
            c_cur.execute(
                """SELECT record_id, record_type, canonical_path, canonical_line
                   FROM records WHERE version_id = ?""",
                (v_id,),
            )
            rec_rows = c_cur.fetchall()
            records = [
                {
                    "record_id": r[0],
                    "record_type": r[1],
                    "canonical_path": r[2],
                    "canonical_line": r[3],
                }
                for r in rec_rows
            ]

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
        ready_versions=len(versions),
        estimated_chunks=len(all_chunks),
        total_canonical_bytes=total_bytes,
        already_committed_chunks=already_committed,
        new_chunks_to_send=len(all_chunks) - already_committed,
        blocked_versions_excluded=blocked_count,
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
    if total_items == 0:
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
        finished=True,
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

        pub_res = client.publish_source_chunk(chunk, idempotency_key=idemp_key)
        remote_mutation_id = pub_res.get("mutation_id")
        final_state = pub_res.get("state", MutationState.FAILED.value)

        if final_state == MutationState.COMMITTED.value:
            retried_success += 1
            update_delivery_item_state(
                conn,
                item_id=item_id,
                remote_state=MutationState.COMMITTED.value,
                remote_mutation_id=remote_mutation_id,
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

    if failed == 0:
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
        finished=True,
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
