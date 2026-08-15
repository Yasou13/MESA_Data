"""
Harvest business logic service.
Provides reusable discovery and bounded collection execution shared across CLI and Web.
"""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from mesa_legal_data.harvest.config import HarvestConfig, load_harvest_config
from mesa_legal_data.harvest.database import get_harvest_db_path
from mesa_legal_data.harvest.discovery.resmi_gazete import ResmiGazeteDiscoveryAdapter
from mesa_legal_data.harvest.discovery_state import (
    finish_discovery_run,
    get_discovery_cursor,
    save_discovery_cursor,
    start_discovery_run,
)
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.queue import enqueue_discovered_document
from mesa_legal_data.harvest.runner import run_harvest_batch
from mesa_legal_data.harvest.selection import evaluate_selection
from mesa_legal_data.sources.request_control import reset_run_budget


def run_discovery_once(
    source_id: str = "resmi_gazete",
    *,
    harvest_cfg: HarvestConfig | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """
    Executes one discovery iteration for a source using cursor tracking.
    Does not print to terminal or raise typer.Exit.
    """
    if harvest_cfg is None:
        harvest_cfg = load_harvest_config()

    if db_path is None:
        db_path = get_harvest_db_path()

    apply_harvest_migrations(db_path)

    src_cfg = harvest_cfg.sources.get(source_id)
    if not src_cfg or not src_cfg.enabled:
        return {
            "status": "skipped",
            "source_id": source_id,
            "mode": None,
            "pages_visited": 0,
            "links_seen": 0,
            "inserted": 0,
            "duplicates": 0,
            "skipped": 0,
            "cursor": {},
            "error": f"Source '{source_id}' is not configured or disabled.",
        }

    run_id = start_discovery_run(source_id, db_path=db_path)
    adapter = ResmiGazeteDiscoveryAdapter()

    today = date.today()
    date_from_str = src_cfg.date_from or "2015-01-01"
    date_to_str = src_cfg.date_to or today.isoformat()

    date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
    date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()

    cursor_data = get_discovery_cursor(source_id, db_path=db_path) or {}

    pages_per_run = src_cfg.budget.discovery_pages_per_run or 50
    urls_per_run = src_cfg.budget.new_urls_per_run or 1000

    pages_visited = 0
    links_seen = 0
    inserted_total = 0
    duplicates_total = 0
    skipped_total = 0

    mode = cursor_data.get("mode", "backfill")
    backfill_next_str = cursor_data.get("backfill_next_date") or cursor_data.get("next_date")
    hwm_str = cursor_data.get("incremental_high_water_mark") or cursor_data.get("last_successful_date")

    if not hwm_str:
        hwm_str = date_to.isoformat()

    dates_to_process: list[date] = []

    if mode == "backfill":
        if backfill_next_str:
            curr = datetime.strptime(backfill_next_str, "%Y-%m-%d").date()
        else:
            curr = date_to

        while curr >= date_from and len(dates_to_process) < pages_per_run:
            dates_to_process.append(curr)
            curr = curr - timedelta(days=1)

        if not dates_to_process or (
            backfill_next_str and datetime.strptime(backfill_next_str, "%Y-%m-%d").date() < date_from
        ):
            mode = "incremental"

    if mode == "incremental" and not dates_to_process:
        try:
            hwm_date = datetime.strptime(hwm_str, "%Y-%m-%d").date()
        except ValueError:
            hwm_date = today
        start_inc = hwm_date + timedelta(days=1)

        curr = start_inc
        while curr <= today and len(dates_to_process) < pages_per_run:
            dates_to_process.append(curr)
            curr = curr + timedelta(days=1)

    error_msg = None
    run_status = "succeeded"

    try:
        for target_date in dates_to_process:
            if pages_visited >= pages_per_run or inserted_total >= urls_per_run:
                break

            docs = adapter.discover_date(target_date)
            pages_visited += 1
            links_seen += len(docs)

            date_inserted = 0
            date_dup = 0
            date_skipped = 0

            for doc in docs:
                decision = evaluate_selection(doc, src_cfg)
                _, res = enqueue_discovered_document(doc, adapter.name, decision, db_path=db_path)
                if res == "inserted":
                    date_inserted += 1
                elif res == "duplicate":
                    date_dup += 1
                else:
                    date_skipped += 1

            inserted_total += date_inserted
            duplicates_total += date_dup
            skipped_total += date_skipped

            if mode == "backfill":
                next_d = target_date - timedelta(days=1)
                is_still_backfill = next_d >= date_from
                save_discovery_cursor(
                    source_id,
                    {
                        "mode": "backfill" if is_still_backfill else "incremental",
                        "backfill_next_date": next_d.isoformat() if is_still_backfill else None,
                        "next_date": next_d.isoformat() if is_still_backfill else None,
                        "incremental_high_water_mark": hwm_str,
                        "last_successful_date": target_date.isoformat(),
                    },
                    db_path=db_path,
                )
            else:
                target_str = target_date.isoformat()
                if target_str > hwm_str:
                    hwm_str = target_str
                save_discovery_cursor(
                    source_id,
                    {
                        "mode": "incremental",
                        "backfill_next_date": None,
                        "next_date": None,
                        "incremental_high_water_mark": hwm_str,
                        "last_successful_date": hwm_str,
                    },
                    db_path=db_path,
                )

    except Exception as e:
        run_status = "failed"
        error_msg = str(e)
    finally:
        reset_run_budget(source_id)
        finish_discovery_run(
            run_id=run_id,
            status=run_status,
            pages_visited=pages_visited,
            links_seen=links_seen,
            items_inserted=inserted_total,
            items_duplicate=duplicates_total,
            items_skipped=skipped_total,
            error_message=error_msg,
            db_path=db_path,
        )

    updated_cursor = get_discovery_cursor(source_id, db_path=db_path) or {}

    return {
        "status": run_status,
        "source_id": source_id,
        "mode": mode,
        "pages_visited": pages_visited,
        "links_seen": links_seen,
        "inserted": inserted_total,
        "duplicates": duplicates_total,
        "skipped": skipped_total,
        "cursor": updated_cursor,
        "error": error_msg,
    }


def run_collection_until_pause(
    source_id: str = "resmi_gazete",
    *,
    harvest_cfg: HarvestConfig | None = None,
    db_path: Path | None = None,
    is_cancelled_cb: Callable[[], bool] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    max_loops: int = 50,
) -> dict[str, Any]:
    """
    Loops through discovery and worker batches safely until a stopping/pause condition is met.
    Never enters an infinite sleep loop.
    """
    if harvest_cfg is None:
        harvest_cfg = load_harvest_config()

    if db_path is None:
        db_path = get_harvest_db_path()

    apply_harvest_migrations(db_path)

    total_processed = 0
    total_succeeded = 0
    total_failed = 0
    total_retry_wait = 0
    total_duplicate = 0
    total_discovered_inserted = 0

    status = "paused"
    stopped_reason = None

    for _ in range(max_loops):
        # 1. Cancellation check before discovery
        if is_cancelled_cb and is_cancelled_cb():
            status = "cancelled"
            stopped_reason = "USER_CANCELLED"
            break

        # 2. Run discovery
        disc = run_discovery_once(source_id=source_id, harvest_cfg=harvest_cfg, db_path=db_path)
        if disc["status"] == "failed":
            status = "failed"
            stopped_reason = f"DISCOVERY_FAILED: {disc.get('error')}"
            break

        total_discovered_inserted += disc.get("inserted", 0)

        if progress_cb:
            progress_cb(
                {
                    "stage": "discovery",
                    "discovery": disc,
                    "processed": total_processed,
                    "succeeded": total_succeeded,
                    "failed": total_failed,
                    "retry_wait": total_retry_wait,
                }
            )

        # 3. Cancellation check after discovery
        if is_cancelled_cb and is_cancelled_cb():
            status = "cancelled"
            stopped_reason = "USER_CANCELLED"
            break

        # 4. Batch worker execution loop
        batch_loop_processed = 0
        while True:
            if is_cancelled_cb and is_cancelled_cb():
                status = "cancelled"
                stopped_reason = "USER_CANCELLED"
                break

            stats = run_harvest_batch(harvest_cfg=harvest_cfg, db_path=db_path)
            p = stats.get("processed", 0)
            s = stats.get("succeeded", 0)
            f = stats.get("failed", 0)
            rw = stats.get("retry_wait", 0)
            dup = stats.get("duplicate", 0)
            reason = stats.get("stopped_reason")

            total_processed += p
            total_succeeded += s
            total_failed += f
            total_retry_wait += rw
            total_duplicate += dup
            batch_loop_processed += p

            if progress_cb and p > 0:
                progress_cb(
                    {
                        "stage": "worker",
                        "batch": stats,
                        "processed": total_processed,
                        "succeeded": total_succeeded,
                        "failed": total_failed,
                        "retry_wait": total_retry_wait,
                    }
                )

            if is_cancelled_cb and is_cancelled_cb():
                status = "cancelled"
                stopped_reason = "USER_CANCELLED"
                break

            if reason:
                stopped_reason = reason
                if reason == "NO_QUEUED_ITEMS":
                    # Queue is empty. If discovery in this loop produced 0 new items and nothing was processed, we are up to date!
                    if disc.get("inserted", 0) == 0 and batch_loop_processed == 0:
                        status = "up_to_date"
                    break
                elif "LOW_DISK" in reason:
                    status = "paused_disk_limit"
                    break
                elif "TARGET_REACHED" in reason or "GLOBAL_TARGET" in reason:
                    status = "target_reached"
                    break
                elif "DAILY_LIMIT" in reason or "BUDGET" in reason:
                    status = "paused_daily_limit"
                    break
                elif "CIRCUIT" in reason or "ERROR_RATE" in reason:
                    status = "paused_safety"
                    break
                else:
                    # Generic stop
                    break

            if p == 0:
                break

        if status in ("cancelled", "failed", "up_to_date", "paused_disk_limit", "target_reached", "paused_daily_limit", "paused_safety"):
            break

        # If discovery found nothing and worker processed nothing, we're up to date
        if disc.get("pages_visited", 0) == 0 and batch_loop_processed == 0:
            status = "up_to_date"
            break

    return {
        "status": status,
        "stopped_reason": stopped_reason or "BATCH_FINISHED",
        "processed": total_processed,
        "succeeded": total_succeeded,
        "failed": total_failed,
        "retry_wait": total_retry_wait,
        "duplicate": total_duplicate,
        "discovered_inserted": total_discovered_inserted,
    }
