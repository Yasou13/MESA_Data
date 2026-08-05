import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream


def log_audit_event(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    reason: str | None = None,
    old_sha256: str | None = None,
    new_sha256: str | None = None,
    details_json: str = "{}",
    request_id: str | None = None,
    event_id: str | None = None,
) -> str:
    if not event_id:
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO audit_events (event_id, actor, action, subject_type, subject_id, old_sha256, new_sha256, reason, details_json, request_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            actor,
            action,
            subject_type,
            subject_id,
            old_sha256,
            new_sha256,
            reason,
            details_json,
            request_id,
            now,
        ),
    )
    return event_id


def audit_event(
    conn: sqlite3.Connection,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    reason: str | None = None,
    old_sha256: str | None = None,
    new_sha256: str | None = None,
    details: str | dict | None = None,
    request_id: str | None = None,
) -> str:
    if isinstance(details, dict):
        det_str = json.dumps(details)
    else:
        det_str = details or "{}"
    return log_audit_event(
        conn,
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        reason=reason,
        old_sha256=old_sha256,
        new_sha256=new_sha256,
        details_json=det_str,
        request_id=request_id,
    )


def run_doctor_check() -> dict[str, Any]:
    """
    Performs system health check:
    - Data root write permissions
    - SQLite database status
    - Missing or corrupted raw files
    - Disk catalog recovery scanning if DB is corrupted or missing
    - Release consistency and recovery checks (.building, .orphaned, disk/catalog mismatch, manifest, item counts)
    """
    settings = load_settings()
    data_root = settings.data_root_path

    missing_artifacts: list[tuple[str, str]] = []
    disk_raw_files: list[str] = []
    disk_canonical_files: list[str] = []

    stale_building_releases: list[str] = []
    orphaned_releases: list[str] = []
    catalog_release_missing_on_disk: list[str] = []
    disk_release_missing_in_catalog: list[str] = []
    manifest_verification_errors: list[str] = []
    release_item_count_mismatches: list[str] = []

    db_file = data_root / "catalog.sqlite"
    db_exists = db_file.exists()
    db_healthy = False
    catalog_releases: dict[str, str] = {}

    if db_exists:
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            cursor.execute("SELECT artifact_id, raw_path FROM artifacts")
            rows = cursor.fetchall()
            for art_id, raw_path in rows:
                full_p = data_root / raw_path
                if not full_p.exists():
                    missing_artifacts.append((art_id, raw_path))

            cursor.execute("SELECT release_id, release_path FROM releases")
            for rel_id, rel_p in cursor.fetchall():
                catalog_releases[rel_id] = rel_p

            conn.close()
            db_healthy = True
        except sqlite3.Error:
            db_healthy = False

    releases_dir = data_root / "releases"
    if releases_dir.exists():
        for p in releases_dir.iterdir():
            if p.is_dir():
                folder_name = p.name
                if folder_name.endswith(".building"):
                    stale_building_releases.append(folder_name)
                elif folder_name.endswith(".orphaned"):
                    orphaned_releases.append(folder_name)
                else:
                    rel_id = folder_name
                    if db_healthy and rel_id not in catalog_releases:
                        disk_release_missing_in_catalog.append(rel_id)

                    manifest_p = p / "manifest.json"
                    if not manifest_p.exists():
                        manifest_verification_errors.append(f"{rel_id}: missing manifest.json")
                    else:
                        try:
                            with open(manifest_p, "r", encoding="utf-8") as f:
                                mdata = json.load(f)
                            records_in_manifest = len(mdata.get("records", []))
                            manifest_claimed_count = mdata.get("counts", {}).get("total_records")
                            if manifest_claimed_count is not None and records_in_manifest != manifest_claimed_count:
                                release_item_count_mismatches.append(
                                    f"{rel_id}: manifest claims {manifest_claimed_count} but contains {records_in_manifest}"
                                )
                        except Exception as e:
                            manifest_verification_errors.append(f"{rel_id}: invalid JSON ({e})")

    if db_healthy:
        for rel_id, rel_p in catalog_releases.items():
            full_rel_path = data_root / rel_p
            if not full_rel_path.exists():
                catalog_release_missing_on_disk.append(rel_id)

    if not db_healthy:
        raw_dir = data_root / "raw"
        if raw_dir.exists():
            for p in raw_dir.glob("**/*"):
                if p.is_file():
                    disk_raw_files.append(str(p.relative_to(data_root)))
        canonical_dir = data_root / "canonical"
        if canonical_dir.exists():
            for p in canonical_dir.glob("**/*"):
                if p.is_file():
                    disk_canonical_files.append(str(p.relative_to(data_root)))

    return {
        "data_root": str(data_root),
        "data_root_writable": os.access(data_root, os.W_OK),
        "catalog_sqlite_exists": db_exists,
        "catalog_sqlite_healthy": db_healthy,
        "missing_artifacts": missing_artifacts,
        "disk_raw_files": disk_raw_files,
        "disk_canonical_files": disk_canonical_files,
        "stale_building_releases": stale_building_releases,
        "orphaned_releases": orphaned_releases,
        "catalog_release_missing_on_disk": catalog_release_missing_on_disk,
        "disk_release_missing_in_catalog": disk_release_missing_in_catalog,
        "manifest_verification_errors": manifest_verification_errors,
        "release_item_count_mismatches": release_item_count_mismatches,
        "recovery_recommended": not db_healthy and (len(disk_raw_files) > 0 or len(disk_canonical_files) > 0),
    }


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
