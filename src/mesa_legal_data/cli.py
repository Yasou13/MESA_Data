import os
from datetime import UTC
from pathlib import Path

import typer

from mesa_legal_data.config import load_settings

app = typer.Typer(help="MESA Legal Data CLI")
collect_app = typer.Typer(help="Collect legal data artifacts from sources.")
app.add_typer(collect_app, name="collect")


@app.command()
def init():
    """Initializes the data root directories."""
    settings = load_settings()
    data_root = settings.data_root_path

    # Create directories
    dirs_to_create = [
        data_root / "raw",
        data_root / "canonical",
        data_root / "releases",
        data_root / "tmp",
    ]

    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)

    # Check write permissions
    if not os.access(data_root, os.W_OK):
        typer.secho(f"Error: No write permission to data root {data_root}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho(f"Data root initialized at {data_root}", fg=typer.colors.GREEN)


@app.command()
def migrate():
    """Runs database migrations."""
    from mesa_legal_data.catalog import migrate as run_migrations

    try:
        run_migrations()
        typer.secho("Database migrations applied successfully.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Migration failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def doctor():
    """Checks the health of the system and catalog."""
    from mesa_legal_data.audit import run_doctor_check

    res = run_doctor_check()
    typer.secho("=== MESA Legal Data Health Check ===", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"Data Root          : {res['data_root']}")
    typer.echo(f"Data Root Writable : {res['data_root_writable']}")
    typer.echo(f"Catalog Database   : {'FOUND' if res['catalog_sqlite_exists'] else 'NOT FOUND'}")

    if res["missing_artifacts"]:
        typer.secho(
            f"WARNING: {len(res['missing_artifacts'])} missing artifacts found!",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho("All artifact files present and accounted for.", fg=typer.colors.GREEN)


@app.command()
def backup(
    target_dir: Path | None = typer.Option(None, "--target-dir", help="Backup output directory"),
):
    """Creates a timestamped backup of the catalog database."""
    from mesa_legal_data.audit import backup_catalog

    try:
        b_file = backup_catalog(backup_dir=target_dir)
        typer.secho(f"Successfully backed up catalog to {b_file}", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Error backing up catalog: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def restore(
    backup_file: Path = typer.Option(..., "--backup-file", help="Path to backup sqlite file"),
):
    """Restores the catalog database from a backup file."""
    from mesa_legal_data.audit import restore_catalog

    try:
        restore_catalog(backup_file)
        typer.secho(f"Successfully restored catalog from {backup_file}", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Error restoring catalog: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def audit():
    """Audits SHA-256 integrity of all raw stored artifacts."""
    from mesa_legal_data.audit import run_integrity_audit

    res = run_integrity_audit()
    typer.secho("=== MESA Legal Data Integrity Audit ===", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"Passed    : {res['passed']}")
    typer.echo(f"Corrupted : {res['corrupted']}")
    typer.echo(f"Missing   : {res['missing']}")

    if res["corrupted"] > 0 or res["missing"] > 0:
        typer.secho("Integrity audit FAILED!", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)
    else:
        typer.secho("Integrity audit PASSED clean.", fg=typer.colors.GREEN, bold=True)


@collect_app.command("manual")
def collect_manual(
    source: str = typer.Option(..., "--source", help="Source ID (e.g., mevzuat, aym, yargitay)"),
    file: Path = typer.Option(..., "--file", help="Path to local file to import"),
    document_id: str = typer.Option(
        ...,
        "--document-id",
        help="Canonical Document ID (e.g. tr:legislation:law:4721)",
    ),
    family: str = typer.Option("legislation", "--family", help="Document family"),
    document_type: str = typer.Option("law", "--document-type", help="Document type"),
    jurisdiction: str = typer.Option("TR", "--jurisdiction", help="Jurisdiction code"),
    title: str | None = typer.Option(None, "--title", help="Document title"),
    stable_key: str | None = typer.Option(None, "--stable-key", help="Stable key for storage path"),
):
    """Imports a local file as a raw artifact."""
    from mesa_legal_data.sources import import_manual_file

    try:
        artifact = import_manual_file(
            file_path=file,
            source_id=source,
            document_id=document_id,
            family=family,
            document_type=document_type,
            jurisdiction=jurisdiction,
            title=title,
            stable_key=stable_key,
        )
        typer.secho(
            f"Successfully imported artifact {artifact.artifact_id} -> {artifact.raw_path}",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error importing manual file: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@collect_app.command("url")
def collect_url(
    source: str = typer.Option(..., "--source", help="Source ID (e.g., mevzuat, aym, yargitay)"),
    url: str = typer.Option(..., "--url", help="URL to fetch document from"),
    document_id: str = typer.Option(..., "--document-id", help="Canonical Document ID"),
    family: str = typer.Option("legislation", "--family", help="Document family"),
    document_type: str = typer.Option("law", "--document-type", help="Document type"),
    jurisdiction: str = typer.Option("TR", "--jurisdiction", help="Jurisdiction code"),
    title: str | None = typer.Option(None, "--title", help="Document title"),
    stable_key: str | None = typer.Option(None, "--stable-key", help="Stable key for storage path"),
):
    """Fetches a document from a URL safely into raw storage."""
    from mesa_legal_data.sources import import_manual_url

    try:
        artifact = import_manual_url(
            url=url,
            source_id=source,
            document_id=document_id,
            family=family,
            document_type=document_type,
            jurisdiction=jurisdiction,
            title=title,
            stable_key=stable_key,
        )
        typer.secho(
            f"Successfully imported URL artifact {artifact.artifact_id} -> {artifact.raw_path}",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error importing URL: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@collect_app.command("seed")
def collect_seed(
    fixtures_dir: Path | None = typer.Option(None, "--fixtures-dir", help="Optional local directory with PDF fixtures"),
):
    """Imports the 12 core seed legislation items."""
    from mesa_legal_data.collectors.seed import run_seed_collection

    try:
        artifacts = run_seed_collection(local_fixtures_dir=fixtures_dir)
        typer.secho(
            f"Successfully collected {len(artifacts)} seed legislation artifacts.",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error collecting seed legislation: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def report():
    """Generates quality and catalog summary report."""
    import sqlite3

    from mesa_legal_data.catalog import get_db_path

    db_path = get_db_path()
    if not db_path.exists():
        typer.secho(f"Catalog database not found at {db_path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM documents")
    doc_count = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM artifacts")
    art_count = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM validation_issues WHERE status = 'open'")
    issue_count = cursor.fetchone()[0]

    typer.secho(
        "=== MESA Legal Data Catalog Quality Report ===",
        fg=typer.colors.CYAN,
        bold=True,
    )
    typer.echo(f"Total Documents: {doc_count}")
    typer.echo(f"Total Artifacts: {art_count}")
    typer.echo(f"Open Issues    : {issue_count}")
    conn.close()


review_app = typer.Typer(help="Review records and versions")
app.add_typer(review_app, name="review")


@review_app.command("list")
def review_list(
    status: str | None = typer.Option(None, "--status", help="Filter by approval status: pending, approved, rejected"),
):
    """Lists records for review."""
    from mesa_legal_data.catalog import get_connection, list_records_by_approval_status

    conn = get_connection()
    recs = list_records_by_approval_status(conn, status=status)
    conn.close()

    typer.secho(
        f"Found {len(recs)} records (status: {status or 'all'}):",
        fg=typer.colors.CYAN,
        bold=True,
    )
    for r in recs:
        typer.echo(
            f"  - [{r['approval_status']}] {r['record_id']} ({r['record_type']}) line {r['canonical_line']} in {r['canonical_path']}"
        )


@review_app.command("show")
def review_show(
    record_id: str = typer.Argument(..., help="Record ID to inspect"),
):
    """Shows record details."""
    from mesa_legal_data.catalog import get_connection, get_record

    conn = get_connection()
    rec = get_record(conn, record_id)
    conn.close()

    if not rec:
        typer.secho(f"Record {record_id} not found", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho(f"=== Record {record_id} ===", fg=typer.colors.CYAN, bold=True)
    for k, v in rec.items():
        typer.echo(f"  {k}: {v}")


@review_app.command("approve")
def review_approve(
    record_id: str = typer.Argument(..., help="Record ID to approve"),
    reviewer: str = typer.Option("reviewer", "--reviewer", help="Reviewer name"),
    note: str | None = typer.Option(None, "--note", help="Approval note"),
):
    """Approves a single record."""
    from mesa_legal_data.catalog import approve_record_with_checks, get_connection

    conn = get_connection()
    try:
        res = approve_record_with_checks(conn, record_id, reviewer, note)
        typer.secho(
            f"Successfully APPROVED record {record_id} (review ID: {res['review_id']})",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error approving record: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    finally:
        conn.close()


@review_app.command("approve-version")
def review_approve_version(
    version_id: str = typer.Argument(..., help="Version ID to approve completely"),
    reviewer: str = typer.Option("reviewer", "--reviewer", help="Reviewer name"),
    note: str | None = typer.Option(None, "--note", help="Approval note"),
):
    """Approves all records under a version."""
    from mesa_legal_data.catalog import approve_version_with_checks, get_connection

    conn = get_connection()
    try:
        res = approve_version_with_checks(conn, version_id, reviewer, note)
        typer.secho(
            f"Successfully APPROVED version {version_id} ({res['approved_records']} records)",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error approving version: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    finally:
        conn.close()


@review_app.command("reject")
def review_reject(
    record_id: str = typer.Argument(..., help="Record ID to reject"),
    reviewer: str = typer.Option("reviewer", "--reviewer", help="Reviewer name"),
    note: str | None = typer.Option(None, "--note", help="Rejection note"),
):
    """Rejects a record."""
    from mesa_legal_data.catalog import get_connection, reject_record_with_checks

    conn = get_connection()
    try:
        res = reject_record_with_checks(conn, record_id, reviewer, note)
        typer.secho(
            f"Successfully REJECTED record {record_id} (review ID: {res['review_id']})",
            fg=typer.colors.YELLOW,
        )
    except Exception as e:
        typer.secho(f"Error rejecting record: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    finally:
        conn.close()


release_app = typer.Typer(help="Manage release packages for MESA consumption.")
app.add_typer(release_app, name="release")


@release_app.command("build")
def release_build(
    release_id: str | None = typer.Option(None, "--release-id", help="Optional release ID"),
):
    """Builds a new release package."""
    from mesa_legal_data.release import build_release

    try:
        manifest = build_release(release_id=release_id)
        typer.secho(
            f"Successfully built release {manifest['release_id']} with manifest SHA {manifest.get('files', {}).get('contents.json')}",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error building release: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@release_app.command("verify")
def release_verify(
    release_id: str = typer.Option(..., "--release-id", help="Release ID to verify"),
):
    """Verifies integrity of a release package."""
    from mesa_legal_data.release import verify_release

    try:
        verify_release(release_id=release_id)
        typer.secho(f"Release {release_id} verification PASSED.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Release verification FAILED: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@release_app.command("publish")
def release_publish(
    release_id: str = typer.Option(..., "--release-id", help="Release ID to publish"),
):
    """Publishes a verified release package."""
    from datetime import datetime

    from mesa_legal_data.catalog import get_connection

    conn = get_connection()
    try:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE releases SET status = 'published', published_at = ? WHERE release_id = ?",
            (now, release_id),
        )
        typer.secho(
            f"Release {release_id} successfully PUBLISHED at {now}.",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error publishing release: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    finally:
        conn.close()


@release_app.command("revoke")
def release_revoke(
    release_id: str = typer.Option(..., "--release-id", help="Release ID to revoke"),
):
    """Revokes a published release package."""
    from mesa_legal_data.catalog import get_connection

    conn = get_connection()
    try:
        conn.execute("UPDATE releases SET status = 'revoked' WHERE release_id = ?", (release_id,))
        typer.secho(f"Release {release_id} successfully REVOKED.", fg=typer.colors.YELLOW)
    except Exception as e:
        typer.secho(f"Error revoking release: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    finally:
        conn.close()


pipeline_app = typer.Typer(help="Execute pipeline operations")
app.add_typer(pipeline_app, name="pipeline")


@pipeline_app.command("run")
def pipeline_run(
    artifact_id: str = typer.Option(..., "--artifact-id", help="Artifact ID to process"),
):
    """Processes an artifact through the parsing, validation, and canonicalization pipeline."""
    from mesa_legal_data.pipeline import process_artifact_pipeline

    try:
        status = process_artifact_pipeline(artifact_id=artifact_id)
        typer.secho(
            f"Pipeline finished with status '{status}' for artifact {artifact_id}.",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Pipeline processing error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@release_app.command("import")
def release_import(
    release_id: str = typer.Option(..., "--release-id", help="Release ID to import into MESA staging DB"),
):
    """Imports a published release package into the MESA staging database."""
    from mesa_legal_data.release.importer import import_release_to_staging

    try:
        res = import_release_to_staging(release_id=release_id)
        typer.secho(
            f"Successfully IMPORTED release {release_id} into staging DB (status: {res['status']})",
            fg=typer.colors.GREEN,
        )
    except Exception as e:
        typer.secho(f"Error importing release: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("provenance")
def provenance_cmd(
    record_id: str = typer.Argument(..., help="Record ID to inspect provenance chain"),
    as_json: bool = typer.Option(False, "--json", help="Output as raw JSON"),
):
    """Inspects full provenance chain for a given record."""
    import json

    from mesa_legal_data.release.importer import get_record_provenance

    prov = get_record_provenance(record_id)
    if not prov:
        typer.secho(f"Record {record_id} not found", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if as_json:
        typer.echo(json.dumps(prov, indent=2, ensure_ascii=False))
    else:
        typer.secho(
            f"=== Provenance Chain for Record {record_id} ===",
            fg=typer.colors.CYAN,
            bold=True,
        )
        for k, v in prov.items():
            typer.echo(f"  {k}: {v}")


if __name__ == "__main__":
    app()
