import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream


def run_doctor_check() -> dict[str, Any]:
    """
    Performs system health check:
    - Data root write permissions
    - SQLite database status
    - Missing or corrupted raw files
    """
    settings = load_settings()
    data_root = settings.data_root_path

    missing_artifacts: list[tuple[str, str]] = []
    results: dict[str, Any] = {
        "data_root": str(data_root),
        "data_root_writable": os.access(data_root, os.W_OK),
        "catalog_sqlite_exists": (data_root / "catalog.sqlite").exists(),
        "missing_artifacts": missing_artifacts,
    }

    if results["catalog_sqlite_exists"]:
        conn = sqlite3.connect(data_root / "catalog.sqlite")
        cursor = conn.cursor()
        cursor.execute("SELECT artifact_id, raw_path FROM artifacts")
        rows = cursor.fetchall()
        for art_id, raw_path in rows:
            full_p = data_root / raw_path
            if not full_p.exists():
                results["missing_artifacts"].append((art_id, raw_path))
        conn.close()

    return results


def backup_catalog(backup_dir: Path | None = None) -> Path:
    """
    Creates a timestamped backup of catalog.sqlite and data metadata.
    """
    settings = load_settings()
    data_root = settings.data_root_path
    db_file = data_root / "catalog.sqlite"

    if not db_file.exists():
        raise FileNotFoundError(f"Cannot backup: Catalog SQLite not found at {db_file}")

    if backup_dir is None:
        backup_dir = data_root.parent / "backups"

    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target_backup = backup_dir / f"catalog_backup_{timestamp}.sqlite"

    # SQLite online backup or copy
    conn = sqlite3.connect(db_file)
    bck = sqlite3.connect(target_backup)
    conn.backup(bck)
    bck.close()
    conn.close()

    return target_backup


def restore_catalog(backup_path: Path) -> bool:
    """
    Restores catalog.sqlite from a backup file.
    """
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found at {backup_path}")

    settings = load_settings()
    target_db = settings.data_root_path / "catalog.sqlite"

    conn = sqlite3.connect(backup_path)
    bck = sqlite3.connect(target_db)
    conn.backup(bck)
    bck.close()
    conn.close()

    return True


def run_integrity_audit() -> dict[str, int]:
    """
    Scans all raw artifacts and re-verifies their SHA-256 hashes.
    """
    settings = load_settings()
    data_root = settings.data_root_path
    db_file = data_root / "catalog.sqlite"

    if not db_file.exists():
        return {"passed": 0, "corrupted": 0, "missing": 0}

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT raw_path, sha256 FROM artifacts")
    rows = cursor.fetchall()
    conn.close()

    passed = 0
    corrupted = 0
    missing = 0

    for raw_path, expected_sha in rows:
        p = data_root / raw_path
        if not p.exists():
            missing += 1
            continue

        with open(p, "rb") as f:
            actual_sha = hash_stream(f)

        if actual_sha.lower() == expected_sha.lower():
            passed += 1
        else:
            corrupted += 1

    return {"passed": passed, "corrupted": corrupted, "missing": missing}
