"""
Web runtime bootstrap module.
Ensures data directories, migrations, and interrupted operations are prepared
idempotently before starting the web server.
"""

from pathlib import Path

from mesa_legal_data.catalog import get_connection
from mesa_legal_data.catalog import migrate as run_catalog_migrations
from mesa_legal_data.config import load_settings
from mesa_legal_data.harvest.database import get_harvest_db_path
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.operations import recover_interrupted_operations


def prepare_web_runtime(custom_data_root: Path | None = None) -> None:
    """
    Idempotently prepares the data root, applies catalog & harvest migrations,
    and recovers interrupted operations.
    """
    settings = load_settings()
    data_root = custom_data_root or settings.data_root_path

    # 1. Ensure required data-root directories
    for d in [
        data_root / "raw",
        data_root / "canonical",
        data_root / "releases",
        data_root / "tmp",
        data_root / "exports",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    # 2. Apply main catalog migrations
    db_path = data_root / "catalog.sqlite"
    run_catalog_migrations(db_path=db_path)

    # 3. Apply harvest migrations
    harvest_db_path = get_harvest_db_path(custom_data_root=data_root)
    apply_harvest_migrations(harvest_db_path)

    # 4. Recover interrupted operations
    conn = get_connection(db_path)
    try:
        recover_interrupted_operations(conn)
    finally:
        conn.close()
