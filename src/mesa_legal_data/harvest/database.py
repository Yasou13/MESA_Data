import sqlite3
from pathlib import Path

from mesa_legal_data.config import load_settings


def get_harvest_db_path(custom_data_root: Path | None = None) -> Path:
    if custom_data_root is not None:
        data_root = custom_data_root
    else:
        settings = load_settings()
        data_root = settings.data_root_path

    harvest_dir = data_root / "harvest"
    harvest_dir.mkdir(parents=True, exist_ok=True)
    return harvest_dir / "harvest.sqlite"


def get_harvest_connection(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = get_harvest_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn
