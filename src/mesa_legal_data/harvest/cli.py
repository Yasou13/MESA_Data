from pathlib import Path
from typing import Optional

import typer

from mesa_legal_data.harvest.config import load_harvest_config
from mesa_legal_data.harvest.database import get_harvest_db_path
from mesa_legal_data.harvest.discovery.manifest import import_manifest_file
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.queue import (
    recover_expired_leases,
    update_item_status,
)
from mesa_legal_data.harvest.reporting import (
    backup_harvest_db,
    get_harvest_failures,
    get_harvest_status_summary,
)
from mesa_legal_data.harvest.runner import run_harvest_batch

harvest_app = typer.Typer(help="MESA Legal Data Harvest Subsystem")


@harvest_app.command("init")
def harvest_init(custom_data_root: Optional[Path] = typer.Option(None, "--data-root", help="Custom data root path")):
    """Initializes harvest.sqlite database and schema."""
    db_path = get_harvest_db_path(custom_data_root)
    apply_harvest_migrations(db_path)
    typer.secho(f"Harvest database initialized successfully at {db_path}", fg=typer.colors.GREEN)


@harvest_app.command("config-check")
def harvest_config_check(config_file: Optional[Path] = typer.Option(None, "--config", help="Path to harvest.yaml")):
    """Checks harvest.yaml configuration validity."""
    try:
        cfg = load_harvest_config(config_file)
        typer.secho("=== Harvest Config Check ===", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"Harvest Enabled   : {cfg.enabled}")
        typer.echo(f"Target Raw Bytes  : {cfg.target.raw_bytes} ({cfg.target.raw_bytes / 1024**3:.2f} GB)")
        typer.echo(f"Min Free Disk     : {cfg.target.minimum_free_disk_bytes / 1024**3:.2f} GB")
        typer.echo(f"Batch Size        : {cfg.runner.batch_size}")
        typer.echo(f"Configured Sources: {list(cfg.sources.keys())}")
        typer.secho("Config check PASSED.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Config check FAILED: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@harvest_app.command("import-manifest")
def harvest_import_manifest(
    file: Path = typer.Option(..., "--file", help="CSV or JSONL manifest file path"),
    config_file: Optional[Path] = typer.Option(None, "--config", help="Path to harvest.yaml"),
):
    """Imports document URLs from a CSV/JSONL manifest into the harvest queue."""
    cfg = load_harvest_config(config_file)
    db_path = get_harvest_db_path()
    apply_harvest_migrations(db_path)

    try:
        stats = import_manifest_file(file, cfg, db_path=db_path)
        typer.secho("=== Manifest Import Summary ===", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"Total Read : {stats['total']}")
        typer.echo(f"Inserted   : {stats['inserted']}")
        typer.echo(f"Duplicate  : {stats['duplicate']}")
        typer.echo(f"Skipped    : {stats['skipped']}")
        typer.secho("Manifest import completed successfully.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Manifest import failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@harvest_app.command("discover")
def harvest_discover(
    source: str = typer.Option("resmi_gazete", "--source", help="Source ID to discover (e.g. resmi_gazete)"),
    config_file: Optional[Path] = typer.Option(None, "--config", help="Path to harvest.yaml"),
):
    """Runs automated discovery for a configured legal source with cursor tracking."""
    from datetime import date, datetime, timedelta

    from mesa_legal_data.harvest.discovery.resmi_gazete import ResmiGazeteDiscoveryAdapter
    from mesa_legal_data.harvest.discovery_state import (
        finish_discovery_run,
        get_discovery_cursor,
        save_discovery_cursor,
        start_discovery_run,
    )
    from mesa_legal_data.harvest.queue import enqueue_discovered_document
    from mesa_legal_data.harvest.selection import evaluate_selection

    cfg = load_harvest_config(config_file)
    db_path = get_harvest_db_path()
    apply_harvest_migrations(db_path)

    src_cfg = cfg.sources.get(source)
    if not src_cfg or not src_cfg.enabled:
        typer.secho(f"Source '{source}' is not configured or disabled.", fg=typer.colors.YELLOW)
        return

    run_id = start_discovery_run(source, db_path=db_path)
    adapter = ResmiGazeteDiscoveryAdapter()

    today = date.today()
    date_from_str = src_cfg.date_from or "2015-01-01"
    date_to_str = src_cfg.date_to or today.isoformat()

    date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
    date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()

    cursor_data = get_discovery_cursor(source, db_path=db_path) or {}

    pages_per_run = src_cfg.budget.discovery_pages_per_run or 50
    urls_per_run = src_cfg.budget.new_urls_per_run or 1000

    pages_visited = 0
    links_seen = 0
    inserted_total = 0
    duplicates_total = 0
    skipped_total = 0

    mode = cursor_data.get("mode", "backfill")
    dates_to_process: list[date] = []

    if mode == "backfill":
        start_d_str = cursor_data.get("next_date")
        if start_d_str:
            curr = datetime.strptime(start_d_str, "%Y-%m-%d").date()
        else:
            curr = date_to

        while curr >= date_from and len(dates_to_process) < pages_per_run:
            dates_to_process.append(curr)
            curr = curr - timedelta(days=1)

        if not dates_to_process:
            mode = "incremental"

    if mode == "incremental" and not dates_to_process:
        last_str = cursor_data.get("last_successful_date")
        if last_str:
            start_inc = datetime.strptime(last_str, "%Y-%m-%d").date() + timedelta(days=1)
        else:
            start_inc = today

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
                save_discovery_cursor(
                    source,
                    {
                        "mode": "backfill" if next_d >= date_from else "incremental",
                        "next_date": next_d.isoformat(),
                        "last_successful_date": target_date.isoformat(),
                    },
                    db_path=db_path,
                )
            else:
                save_discovery_cursor(
                    source,
                    {
                        "mode": "incremental",
                        "last_successful_date": target_date.isoformat(),
                    },
                    db_path=db_path,
                )

    except Exception as e:
        run_status = "failed"
        error_msg = str(e)
        typer.secho(f"Discovery failed: {e}", fg=typer.colors.RED)
    finally:
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

    if run_status == "failed":
        raise typer.Exit(code=1)

    typer.secho(f"=== Discovery Summary ({source}) ===", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"Pages Visited : {pages_visited}")
    typer.echo(f"Links Seen    : {links_seen}")
    typer.echo(f"Inserted      : {inserted_total}")
    typer.echo(f"Duplicates    : {duplicates_total}")
    typer.echo(f"Skipped       : {skipped_total}")


@harvest_app.command("run")
def harvest_run(
    once: bool = typer.Option(False, "--once", help="Run single batch and exit"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Max batch items limit"),
    config_file: Optional[Path] = typer.Option(None, "--config", help="Path to harvest.yaml"),
):
    """Executes a harvest worker batch."""
    cfg = load_harvest_config(config_file)
    db_path = get_harvest_db_path()
    apply_harvest_migrations(db_path)

    stats = run_harvest_batch(harvest_cfg=cfg, batch_limit=limit, db_path=db_path)
    typer.secho("=== Harvest Batch Execution Summary ===", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"Processed : {stats['processed']}")
    typer.echo(f"Succeeded : {stats['succeeded']}")
    typer.echo(f"Failed    : {stats['failed']}")
    typer.echo(f"Retry Wait: {stats['retry_wait']}")
    if stats.get("stopped_reason"):
        typer.secho(f"Stopped Reason: {stats['stopped_reason']}", fg=typer.colors.YELLOW)
    else:
        typer.secho("Batch finished clean.", fg=typer.colors.GREEN)


@harvest_app.command("status")
def harvest_status():
    """Prints harvest queue status summary."""
    db_path = get_harvest_db_path()
    if not db_path.exists():
        typer.secho("Harvest database does not exist. Run 'mesa-data harvest init' first.", fg=typer.colors.YELLOW)
        return

    res = get_harvest_status_summary(db_path=db_path)
    typer.secho("=== MESA Harvest Status ===", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"Total Queue Items: {res['total_items']}")
    typer.echo(f"Total Raw Bytes  : {res['total_raw_bytes']} ({res['total_raw_bytes'] / 1024**2:.2f} MB)")
    typer.echo("Status Breakdowns:")
    for status, count in res["status_counts"].items():
        typer.echo(f"  - {status:15s}: {count}")


@harvest_app.command("failures")
def harvest_failures(
    limit: int = typer.Option(20, "--limit", help="Max failure records to display"),
):
    """Displays recent failed or retry_wait harvest items."""
    db_path = get_harvest_db_path()
    if not db_path.exists():
        typer.secho("Harvest database not found.", fg=typer.colors.YELLOW)
        return

    failures = get_harvest_failures(limit=limit, db_path=db_path)
    typer.secho(f"=== Recent Harvest Failures ({len(failures)}) ===", fg=typer.colors.CYAN, bold=True)
    for f in failures:
        typer.echo(
            f"ID: {f['id']} | QueueID: {f['queue_id']} | Status: {f['status']} | Code: {f['last_error_code']}\n"
            f"  URL: {f['normalized_url']}\n"
            f"  Error: {f['last_error_message']}\n"
        )


@harvest_app.command("retry")
def harvest_retry(
    item_id: int = typer.Option(..., "--item-id", help="Harvest item ID to retry"),
):
    """Resets a failed/retry_wait item back to queued status."""
    db_path = get_harvest_db_path()
    try:
        update_item_status(item_id, "queued", db_path=db_path)
        typer.secho(f"Item {item_id} reset to queued status.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Error retrying item {item_id}: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@harvest_app.command("recover")
def harvest_recover():
    """Reclaims expired leases back to queued status."""
    db_path = get_harvest_db_path()
    if not db_path.exists():
        typer.secho("Harvest database not found.", fg=typer.colors.YELLOW)
        return

    recovered = recover_expired_leases(db_path=db_path)
    typer.secho(f"Successfully recovered {recovered} expired leased items.", fg=typer.colors.GREEN)


@harvest_app.command("backup")
def harvest_backup(
    target_dir: Optional[Path] = typer.Option(None, "--target-dir", help="Backup directory"),
):
    """Creates a timestamped backup of harvest.sqlite."""
    try:
        b_file = backup_harvest_db(backup_dir=target_dir)
        typer.secho(f"Successfully backed up harvest.sqlite to {b_file}", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Error backing up harvest database: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@harvest_app.command("maintenance")
def harvest_maintenance():
    """Runs harvest system maintenance: recovers expired leases, backups DB, and checks queue status."""
    db_path = get_harvest_db_path()
    if not db_path.exists():
        typer.secho("Harvest database not found.", fg=typer.colors.YELLOW)
        return

    typer.secho("=== MESA Harvest Maintenance ===", fg=typer.colors.CYAN, bold=True)
    recovered = recover_expired_leases(db_path=db_path)
    typer.echo(f"Expired leases reclaimed: {recovered}")

    try:
        b_file = backup_harvest_db(db_path=db_path)
        typer.echo(f"Harvest DB backup created: {b_file}")
    except Exception as e:
        typer.secho(f"Backup warning: {e}", fg=typer.colors.YELLOW)

    res = get_harvest_status_summary(db_path=db_path)
    typer.echo(f"Total Queue Items: {res['total_items']}")
    typer.secho("Maintenance completed successfully.", fg=typer.colors.GREEN)
