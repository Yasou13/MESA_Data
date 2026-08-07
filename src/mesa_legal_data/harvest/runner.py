import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.harvest.budgets import (
    check_free_disk_space,
    check_source_error_circuit_breaker,
    get_daily_budget_usage,
    get_total_raw_bytes,
    record_daily_budget,
)
from mesa_legal_data.harvest.config import HarvestConfig, load_harvest_config
from mesa_legal_data.harvest.models import ItemStatus
from mesa_legal_data.harvest.queue import (
    acquire_lease_batch,
    record_attempt,
    recover_expired_leases,
    update_item_status,
)
from mesa_legal_data.harvest.retry import calculate_next_retry
from mesa_legal_data.harvest.service_bridge import (
    ServiceBridgeError,
    collect_url_item,
    run_pipeline_item,
)


def run_harvest_batch(
    harvest_cfg: HarvestConfig | None = None,
    worker_id: str | None = None,
    batch_limit: int | None = None,
    db_path: Path | None = None,
    sources_yaml_path: Path | None = None,
    custom_data_root: Path | None = None,
) -> dict[str, Any]:
    if harvest_cfg is None:
        harvest_cfg = load_harvest_config()

    if not harvest_cfg.enabled:
        return {"processed": 0, "stopped_reason": "HARVEST_DISABLED"}

    if worker_id is None:
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"

    batch_size = batch_limit if batch_limit else harvest_cfg.runner.batch_size

    # 1. Recover expired leases
    recover_expired_leases(db_path=db_path)

    # 2. Check disk space
    disk_ok, free_bytes = check_free_disk_space(
        minimum_free_bytes=harvest_cfg.target.minimum_free_disk_bytes,
        custom_data_root=custom_data_root,
    )
    if not disk_ok:
        return {
            "processed": 0,
            "stopped_reason": f"LOW_DISK_SPACE (free: {free_bytes} < min: {harvest_cfg.target.minimum_free_disk_bytes})",
        }

    # 3. Check global target
    total_raw = get_total_raw_bytes(db_path=db_path)
    if harvest_cfg.target.stop_when_target_reached and total_raw >= harvest_cfg.target.raw_bytes:
        return {
            "processed": 0,
            "stopped_reason": f"GLOBAL_TARGET_REACHED ({total_raw} >= {harvest_cfg.target.raw_bytes})",
        }

    # 4. Acquire lease batch
    items = acquire_lease_batch(
        worker_id=worker_id,
        batch_size=batch_size,
        lease_seconds=harvest_cfg.runner.lease_seconds,
        db_path=db_path,
    )

    if not items:
        return {"processed": 0, "stopped_reason": "NO_QUEUED_ITEMS"}

    processed_count = 0
    succeeded_count = 0
    failed_count = 0
    retry_wait_count = 0
    duplicate_count = 0

    for item in items:
        if item.id is None:
            continue
        item_id: int = item.id
        # Check source circuit breaker
        if check_source_error_circuit_breaker(
            item.source_id, threshold=harvest_cfg.runner.stop_on_error_rate, db_path=db_path
        ):
            update_item_status(item_id, ItemStatus.QUEUED, db_path=db_path)
            continue

        # Check source daily budget if source is configured
        src_cfg = harvest_cfg.sources.get(item.source_id)
        if src_cfg:
            daily_usage = get_daily_budget_usage(item.source_id, db_path=db_path)
            if daily_usage["documents_downloaded"] >= src_cfg.budget.daily_documents:
                update_item_status(item_id, ItemStatus.QUEUED, db_path=db_path)
                continue
            if daily_usage["raw_bytes_downloaded"] >= src_cfg.budget.daily_raw_bytes:
                update_item_status(item_id, ItemStatus.QUEUED, db_path=db_path)
                continue

        processed_count += 1
        start_iso = datetime.now(UTC).isoformat()
        item_attempts: int = item.attempts if item.attempts is not None else 0
        current_attempt: int = item_attempts + 1

        try:
            # Step A: Download / Collect
            update_item_status(item_id, ItemStatus.DOWNLOADING, db_path=db_path)

            collect_res = collect_url_item(item, sources_yaml_path=sources_yaml_path)

            finish_iso = datetime.now(UTC).isoformat()
            record_attempt(
                item_id=item_id,
                attempt_number=current_attempt,
                stage="download",
                started_at=start_iso,
                finished_at=finish_iso,
                result="succeeded",
                bytes_received=collect_res.byte_size,
                artifact_id=collect_res.artifact_id,
                db_path=db_path,
            )

            update_item_status(
                item_id,
                ItemStatus.DOWNLOADED,
                artifact_id=collect_res.artifact_id,
                raw_bytes=collect_res.byte_size,
                db_path=db_path,
            )

            # Step B: Pipeline run
            if harvest_cfg.runner.pipeline_after_download:
                update_item_status(item_id, ItemStatus.PROCESSING, db_path=db_path)
                pipe_start_iso = datetime.now(UTC).isoformat()

                pipe_res = run_pipeline_item(collect_res.artifact_id)

                pipe_finish_iso = datetime.now(UTC).isoformat()
                record_attempt(
                    item_id=item_id,
                    attempt_number=current_attempt,
                    stage="pipeline",
                    started_at=pipe_start_iso,
                    finished_at=pipe_finish_iso,
                    result="succeeded",
                    artifact_id=collect_res.artifact_id,
                    db_path=db_path,
                )

                # Set final state based on pipeline output (needs_review or completed)
                final_status = ItemStatus.NEEDS_REVIEW if pipe_res.status == "needs_review" else ItemStatus.COMPLETED
                update_item_status(
                    item_id,
                    final_status,
                    version_id=pipe_res.version_id,
                    db_path=db_path,
                )
            else:
                update_item_status(item_id, ItemStatus.COMPLETED, db_path=db_path)

            record_daily_budget(
                item.source_id,
                collect_res.byte_size,
                success=True,
                db_path=db_path,
            )
            succeeded_count += 1

        except ServiceBridgeError as sbe:
            finish_iso = datetime.now(UTC).isoformat()
            record_attempt(
                item_id=item_id,
                attempt_number=current_attempt,
                stage="runner",
                started_at=start_iso,
                finished_at=finish_iso,
                result="failed",
                error_code=sbe.code,
                error_message=sbe.message,
                db_path=db_path,
            )

            record_daily_budget(item.source_id, 0, success=False, db_path=db_path)

            next_retry, should_retry = calculate_next_retry(
                current_attempt, sbe.code, max_attempts=harvest_cfg.runner.max_attempts
            )

            if should_retry:
                update_item_status(
                    item_id,
                    ItemStatus.RETRY_WAIT,
                    last_error_code=sbe.code,
                    last_error_message=sbe.message,
                    next_retry_at=next_retry,
                    db_path=db_path,
                )
                retry_wait_count += 1
            else:
                target_terminal = (
                    ItemStatus.BLOCKED
                    if sbe.code in ("SOURCE_HOST_NOT_ALLOWED", "PRIVATE_IP_NOT_ALLOWED")
                    else ItemStatus.FAILED
                )
                update_item_status(
                    item_id,
                    target_terminal,
                    last_error_code=sbe.code,
                    last_error_message=sbe.message,
                    db_path=db_path,
                )
                failed_count += 1
        except Exception as ex:
            finish_iso = datetime.now(UTC).isoformat()
            err_msg = str(ex)
            err_code = "UNEXPECTED_ERROR"

            record_attempt(
                item_id=item_id,
                attempt_number=current_attempt,
                stage="runner",
                started_at=start_iso,
                finished_at=finish_iso,
                result="failed",
                error_code=err_code,
                error_message=err_msg,
                db_path=db_path,
            )

            next_retry, should_retry = calculate_next_retry(
                current_attempt, err_code, max_attempts=harvest_cfg.runner.max_attempts
            )

            if should_retry:
                update_item_status(
                    item_id,
                    ItemStatus.RETRY_WAIT,
                    last_error_code=err_code,
                    last_error_message=err_msg,
                    next_retry_at=next_retry,
                    db_path=db_path,
                )
                retry_wait_count += 1
            else:
                update_item_status(
                    item_id,
                    ItemStatus.FAILED,
                    last_error_code=err_code,
                    last_error_message=err_msg,
                    db_path=db_path,
                )
                failed_count += 1

    return {
        "processed": processed_count,
        "succeeded": succeeded_count,
        "failed": failed_count,
        "retry_wait": retry_wait_count,
        "duplicate": duplicate_count,
        "stopped_reason": None,
    }
