import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.harvest.budgets import (
    check_free_disk_space,
    check_source_error_circuit_breaker,
    get_daily_budget_usage,
    get_source_total_raw_bytes,
    get_total_raw_bytes,
    record_download_budget,
    record_pipeline_budget,
)
from mesa_legal_data.harvest.config import HarvestConfig, load_harvest_config
from mesa_legal_data.harvest.models import ItemStatus
from mesa_legal_data.harvest.queue import (
    acquire_lease_batch,
    increment_item_attempts,
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

    start_monotonic = time.monotonic()

    for idx, item in enumerate(items):
        if item.id is None:
            continue
        item_id: int = item.id

        # Check max runtime
        elapsed = time.monotonic() - start_monotonic
        if elapsed >= harvest_cfg.runner.max_runtime_seconds:
            # Requeue remaining leased items to leave no stranded leases
            for rem in items[idx:]:
                if rem.id is not None:
                    update_item_status(rem.id, ItemStatus.QUEUED, db_path=db_path)
            return {
                "processed": processed_count,
                "succeeded": succeeded_count,
                "failed": failed_count,
                "retry_wait": retry_wait_count,
                "duplicate": duplicate_count,
                "stopped_reason": f"MAX_RUNTIME_REACHED ({harvest_cfg.runner.max_runtime_seconds}s)",
            }

        # Check source circuit breaker
        if check_source_error_circuit_breaker(
            item.source_id, threshold=harvest_cfg.runner.stop_on_error_rate, db_path=db_path
        ):
            update_item_status(item_id, ItemStatus.QUEUED, db_path=db_path)
            continue

        # Check source daily and total budgets if source is configured
        src_cfg = harvest_cfg.sources.get(item.source_id)
        if src_cfg:
            src_total_raw = get_source_total_raw_bytes(item.source_id, db_path=db_path)
            if src_total_raw >= src_cfg.budget.target_raw_bytes:
                for rem in items[idx:]:
                    if rem.id is not None:
                        update_item_status(rem.id, ItemStatus.QUEUED, db_path=db_path)
                return {
                    "processed": processed_count,
                    "succeeded": succeeded_count,
                    "failed": failed_count,
                    "retry_wait": retry_wait_count,
                    "duplicate": duplicate_count,
                    "stopped_reason": f"SOURCE_TARGET_REACHED ({item.source_id})",
                }

            daily_usage = get_daily_budget_usage(item.source_id, db_path=db_path)
            if daily_usage["documents_downloaded"] >= src_cfg.budget.daily_documents:
                update_item_status(item_id, ItemStatus.QUEUED, db_path=db_path)
                continue
            if daily_usage["raw_bytes_downloaded"] >= src_cfg.budget.daily_raw_bytes:
                update_item_status(item_id, ItemStatus.QUEUED, db_path=db_path)
                continue

        processed_count += 1
        start_iso = datetime.now(UTC).isoformat()
        current_attempt: int = increment_item_attempts(item_id, db_path=db_path)

        try:
            from mesa_legal_data.harvest.queue import _check_artifact_committed, _check_canonical_committed

            artifact_id: str | None = item.artifact_id
            skip_download = False

            if artifact_id and _check_artifact_committed(artifact_id):
                skip_download = True

            if not skip_download:
                # Step A: Download / Collect
                update_item_status(item_id, ItemStatus.DOWNLOADING, db_path=db_path)

                collect_res = collect_url_item(item, sources_yaml_path=sources_yaml_path)
                artifact_id = collect_res.artifact_id

                if collect_res.duplicate:
                    has_canon, canon_st, _ = _check_canonical_committed(artifact_id, db_path=db_path)
                    if has_canon:
                        finish_iso = datetime.now(UTC).isoformat()
                        record_attempt(
                            item_id=item_id,
                            attempt_number=current_attempt,
                            stage="download",
                            started_at=start_iso,
                            finished_at=finish_iso,
                            result="duplicate",
                            bytes_received=0,
                            artifact_id=artifact_id,
                            db_path=db_path,
                        )
                        update_item_status(
                            item_id,
                            ItemStatus.DUPLICATE,
                            artifact_id=artifact_id,
                            raw_bytes=collect_res.byte_size,
                            db_path=db_path,
                        )
                        duplicate_count += 1
                        record_download_budget(
                            item.source_id,
                            raw_bytes=0,
                            duplicate=True,
                            db_path=db_path,
                        )
                        continue
                    # Duplicate raw artifact but missing canonical processing -> continue to pipeline

                finish_iso = datetime.now(UTC).isoformat()
                record_attempt(
                    item_id=item_id,
                    attempt_number=current_attempt,
                    stage="download",
                    started_at=start_iso,
                    finished_at=finish_iso,
                    result="succeeded",
                    bytes_received=collect_res.byte_size,
                    artifact_id=artifact_id,
                    db_path=db_path,
                )

                update_item_status(
                    item_id,
                    ItemStatus.DOWNLOADED,
                    artifact_id=artifact_id,
                    raw_bytes=collect_res.byte_size,
                    db_path=db_path,
                )

                record_download_budget(
                    item.source_id,
                    raw_bytes=collect_res.byte_size,
                    duplicate=False,
                    db_path=db_path,
                )

            # Step B: Pipeline run
            if harvest_cfg.runner.pipeline_after_download:
                update_item_status(item_id, ItemStatus.PROCESSING, db_path=db_path)
                pipe_start_iso = datetime.now(UTC).isoformat()

                pipe_res = run_pipeline_item(artifact_id)

                pipe_finish_iso = datetime.now(UTC).isoformat()
                pipe_success = pipe_res.status in ("approved", "needs_review", "rejected")

                record_attempt(
                    item_id=item_id,
                    attempt_number=current_attempt,
                    stage="pipeline",
                    started_at=pipe_start_iso,
                    finished_at=pipe_finish_iso,
                    result="succeeded" if pipe_success else "failed",
                    error_code=None
                    if pipe_success
                    else ("PIPELINE_FAILED" if pipe_res.status == "failed" else "UNEXPECTED_PIPELINE_STATUS"),
                    error_message=None if pipe_success else f"Pipeline status: {pipe_res.status}",
                    artifact_id=collect_res.artifact_id,
                    db_path=db_path,
                )

                record_pipeline_budget(
                    item.source_id,
                    success=pipe_success,
                    db_path=db_path,
                )

                if pipe_res.status == "approved":
                    update_item_status(
                        item_id,
                        ItemStatus.COMPLETED,
                        version_id=pipe_res.version_id,
                        db_path=db_path,
                    )
                    succeeded_count += 1
                elif pipe_res.status in ("needs_review", "rejected"):
                    update_item_status(
                        item_id,
                        ItemStatus.NEEDS_REVIEW,
                        version_id=pipe_res.version_id,
                        db_path=db_path,
                    )
                    succeeded_count += 1
                elif pipe_res.status == "failed":
                    update_item_status(
                        item_id,
                        ItemStatus.FAILED,
                        last_error_code="PIPELINE_FAILED",
                        last_error_message="Pipeline execution returned failed status",
                        db_path=db_path,
                    )
                    failed_count += 1
                else:
                    update_item_status(
                        item_id,
                        ItemStatus.FAILED,
                        last_error_code="UNEXPECTED_PIPELINE_STATUS",
                        last_error_message=f"Pipeline returned unexpected status: {pipe_res.status}",
                        db_path=db_path,
                    )
                    failed_count += 1
            else:
                record_pipeline_budget(item.source_id, success=True, db_path=db_path)
                update_item_status(item_id, ItemStatus.COMPLETED, db_path=db_path)
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

            record_download_budget(item.source_id, 0, duplicate=False, db_path=db_path)

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
