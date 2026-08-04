import os
from pathlib import Path
from typing import Optional

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

    if res['missing_artifacts']:
        typer.secho(f"WARNING: {len(res['missing_artifacts'])} missing artifacts found!", fg=typer.colors.YELLOW)
    else:
        typer.secho("All artifact files present and accounted for.", fg=typer.colors.GREEN)


@app.command()
def backup(
    target_dir: Optional[Path] = typer.Option(None, "--target-dir", help="Backup output directory"),
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

    if res['corrupted'] > 0 or res['missing'] > 0:
        typer.secho("Integrity audit FAILED!", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)
    else:
        typer.secho("Integrity audit PASSED clean.", fg=typer.colors.GREEN, bold=True)


@collect_app.command("manual")
def collect_manual(
    source: str = typer.Option(..., "--source", help="Source ID (e.g., mevzuat, aym, yargitay)"),
    file: Path = typer.Option(..., "--file", help="Path to local file to import"),
    document_id: str = typer.Option(..., "--document-id", help="Canonical Document ID (e.g. tr:legislation:law:4721)"),
    family: str = typer.Option("legislation", "--family", help="Document family"),
    document_type: str = typer.Option("law", "--document-type", help="Document type"),
    jurisdiction: str = typer.Option("TR", "--jurisdiction", help="Jurisdiction code"),
    title: Optional[str] = typer.Option(None, "--title", help="Document title"),
    stable_key: Optional[str] = typer.Option(None, "--stable-key", help="Stable key for storage path"),
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
    title: Optional[str] = typer.Option(None, "--title", help="Document title"),
    stable_key: Optional[str] = typer.Option(None, "--stable-key", help="Stable key for storage path"),
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
    fixtures_dir: Optional[Path] = typer.Option(None, "--fixtures-dir", help="Optional local directory with PDF fixtures"),
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

    typer.secho("=== MESA Legal Data Catalog Quality Report ===", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"Total Documents: {doc_count}")
    typer.echo(f"Total Artifacts: {art_count}")
    typer.echo(f"Open Issues    : {issue_count}")
    conn.close()


@app.command()
def review(
    issue_id: str = typer.Option(..., "--issue-id", help="ID of validation issue to review"),
    action: str = typer.Option("resolve", "--action", help="Action to perform: resolve or waive"),
    by: str = typer.Option("reviewer", "--by", help="Reviewer name"),
    note: Optional[str] = typer.Option(None, "--note", help="Resolution note"),
):
    """Reviews and resolves open validation or privacy issues."""
    import sqlite3
    from mesa_legal_data.catalog import get_connection, resolve_issue

    conn = get_connection()
    try:
        status_target = "resolved" if action == "resolve" else "waived"
        resolve_issue(conn, issue_id=issue_id, status=status_target, resolved_by=by, resolution_note=note)
        typer.secho(f"Successfully updated issue {issue_id} to status '{status_target}' by {by}.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Error reviewing issue: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    finally:
        conn.close()


release_app = typer.Typer(help="Manage release packages for MESA consumption.")
app.add_typer(release_app, name="release")


@release_app.command("build")
def release_build(
    release_id: Optional[str] = typer.Option(None, "--release-id", help="Optional release ID"),
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
    import sqlite3
    from datetime import datetime, timezone
    from mesa_legal_data.catalog import get_connection

    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE releases SET status = 'published', published_at = ? WHERE release_id = ?",
            (now, release_id),
        )
        typer.secho(f"Release {release_id} successfully PUBLISHED at {now}.", fg=typer.colors.GREEN)
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
    import sqlite3
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


@release_app.command("rollback")
def release_rollback(
    release_id: str = typer.Option(..., "--release-id", help="Release ID to rollback"),
):
    """Rolls back a release package."""
    from mesa_legal_data.release import rollback_release

    try:
        rollback_release(release_id)
        typer.secho(f"Release {release_id} successfully ROLLED BACK.", fg=typer.colors.YELLOW)
    except Exception as e:
        typer.secho(f"Error rolling back release: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
