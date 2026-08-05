import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.catalog import (
    create_release,
    get_connection,
    iter_records_for_release,
    list_open_blocking_issues,
)
from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.release.verifier import verify_release_directory
from mesa_legal_data.schema_validation import validate_record


class ReleaseBuildError(Exception):
    pass


def json_str_deterministic(rec: dict[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_release(release_id: str | None = None) -> dict[str, Any]:
    """
    Builds a release package from approved canonical records using a real streaming architecture.
    - O(n) single-pass sequential reading of canonical part files
    - Temporary SQLite spool for sorting and payload staging (zero RAM accumulation of payloads)
    - Direct streaming write to output JSONL files
    - Atomic rename and verified catalog registration
    """
    settings = load_settings()
    data_root = settings.data_root_path

    if not release_id:
        now_str = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        release_id = f"release-{now_str}"

    final_dir = data_root / "releases" / release_id
    if final_dir.exists():
        raise ReleaseBuildError(f"Release directory already exists for release_id '{release_id}'")

    building_dir = data_root / "releases" / f".building-{release_id}-{uuid.uuid4().hex[:8]}"
    building_dir.mkdir(parents=True, exist_ok=True)
    building_data_dir = building_dir / "data"
    building_data_dir.mkdir(parents=True, exist_ok=True)
    building_schemas_dir = building_dir / "schemas"
    building_schemas_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()

    # Temporary SQLite spool DB for metadata and payload staging
    spool_db_path = building_dir / f".spool-{uuid.uuid4().hex[:8]}.sqlite"
    spool_conn = sqlite3.connect(spool_db_path)
    spool_conn.execute("PRAGMA journal_mode = WAL;")
    spool_conn.execute("PRAGMA synchronous = NORMAL;")
    spool_conn.execute("PRAGMA temp_store = FILE;")

    spool_conn.executescript("""
        CREATE TABLE selected_records (
            record_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            record_sha256 TEXT NOT NULL,
            canonical_path TEXT NOT NULL,
            canonical_line INTEGER NOT NULL,
            version_id TEXT NOT NULL,
            PRIMARY KEY (canonical_path, canonical_line)
        );

        CREATE TABLE payload_spool (
            record_type TEXT NOT NULL,
            record_id TEXT NOT NULL,
            record_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (record_type, record_id)
        );
    """)

    try:
        # 1. Check open blocker issues
        blockers = list_open_blocking_issues(conn)
        if blockers:
            raise ReleaseBuildError(f"Cannot build release: open blocker issues exist: {blockers}")

        # 2. Stream selected record metadata from catalog into temporary selected_records table
        selected_batch = []
        batch_size = 2000
        for ref in iter_records_for_release(conn, batch_size=batch_size):
            selected_batch.append(
                (
                    ref.record_id,
                    ref.record_type,
                    ref.record_sha256,
                    ref.canonical_path,
                    ref.canonical_line,
                    ref.version_id,
                )
            )
            if len(selected_batch) >= batch_size:
                spool_conn.executemany(
                    "INSERT INTO selected_records (record_id, record_type, record_sha256, canonical_path, canonical_line, version_id) VALUES (?, ?, ?, ?, ?, ?)",
                    selected_batch,
                )
                selected_batch.clear()

        if selected_batch:
            spool_conn.executemany(
                "INSERT INTO selected_records (record_id, record_type, record_sha256, canonical_path, canonical_line, version_id) VALUES (?, ?, ?, ?, ?, ?)",
                selected_batch,
            )
            selected_batch.clear()

        spool_conn.commit()

        # 3. O(n) Single Sequential Pass over Canonical Part Files
        # Group selected records by canonical_path ordered by canonical_line
        path_cur = spool_conn.cursor()
        path_cur.execute("SELECT DISTINCT canonical_path FROM selected_records ORDER BY canonical_path ASC")
        canonical_paths = []
        while True:
            rows = path_cur.fetchmany(2000)
            if not rows:
                break
            for r in rows:
                canonical_paths.append(r[0])

        payload_batch = []

        for rel_c_path in canonical_paths:
            c_abs_path = data_root / rel_c_path
            if not c_abs_path.exists():
                raise ReleaseBuildError(f"Canonical file missing for release: {c_abs_path}")

            line_cur = spool_conn.cursor()
            line_cur.execute(
                "SELECT canonical_line, record_id, record_type, record_sha256 FROM selected_records WHERE canonical_path = ? ORDER BY canonical_line ASC",
                (rel_c_path,),
            )

            # Read file sequentially in a single pass
            with open(c_abs_path, "r", encoding="utf-8") as f:
                current_target = line_cur.fetchone()
                for line_idx, line in enumerate(f, start=1):
                    while current_target and current_target[0] == line_idx:
                        target_line_num, expected_r_id, expected_r_type, expected_hash = current_target

                        actual_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()
                        if actual_hash.lower() != expected_hash.lower():
                            raise ReleaseBuildError(
                                f"Record hash mismatch for {expected_r_id}: expected {expected_hash}, got {actual_hash}"
                            )

                        line_str = line.strip()
                        rec_obj = json.loads(line_str)
                        validate_record(rec_obj)

                        if rec_obj["id"] != expected_r_id:
                            raise ReleaseBuildError(
                                f"Record ID mismatch at line {line_idx} in {c_abs_path}: expected {expected_r_id}, got {rec_obj['id']}"
                            )

                        if rec_obj["record_type"] != expected_r_type:
                            raise ReleaseBuildError(
                                f"Record type mismatch at line {line_idx} in {c_abs_path}: expected {expected_r_type}, got {rec_obj['record_type']}"
                            )

                        det_payload = json_str_deterministic(rec_obj)
                        payload_batch.append((expected_r_type, expected_r_id, expected_hash, det_payload))

                        if len(payload_batch) >= batch_size:
                            spool_conn.executemany(
                                "INSERT INTO payload_spool (record_type, record_id, record_sha256, payload_json) VALUES (?, ?, ?, ?)",
                                payload_batch,
                            )
                            payload_batch.clear()

                        current_target = line_cur.fetchone()

                    if not current_target:
                        break

                if current_target:
                    raise ReleaseBuildError(f"Line number {current_target[0]} out of bounds in {c_abs_path}")

        if payload_batch:
            spool_conn.executemany(
                "INSERT INTO payload_spool (record_type, record_id, record_sha256, payload_json) VALUES (?, ?, ?, ?)",
                payload_batch,
            )
            payload_batch.clear()

        spool_conn.commit()

        # 4. Stream output JSONL files deterministically ordered by record_id
        type_to_filename = {
            "legislation": "data/legislation.jsonl",
            "article": "data/articles.jsonl",
            "decision": "data/decisions.jsonl",
            "citation": "data/citations.jsonl",
        }
        counts_dict = {"legislation_count": 0, "article_count": 0, "decision_count": 0, "citation_count": 0}
        file_manifest_entries: dict[str, str] = {}

        for r_type, fn in type_to_filename.items():
            out_file = building_dir / fn
            count_key = f"{r_type}_count"
            actual_type_count = 0

            out_cur = spool_conn.cursor()
            out_cur.execute(
                "SELECT payload_json FROM payload_spool WHERE record_type = ? ORDER BY record_id ASC",
                (r_type,),
            )

            with open(out_file, "w", encoding="utf-8") as f:
                while True:
                    rows = out_cur.fetchmany(batch_size)
                    if not rows:
                        break
                    for r in rows:
                        f.write(r[0] + "\n")
                        actual_type_count += 1
                f.flush()
                os.fsync(f.fileno())

            counts_dict[count_key] = actual_type_count

            with open(out_file, "rb") as f:
                file_manifest_entries[fn] = hash_stream(f)

        # 5. Copy schema files
        project_schemas_dir = Path(__file__).parent.parent.parent.parent / "schemas"
        if project_schemas_dir.exists():
            for schema_path in sorted(list(project_schemas_dir.glob("*.schema.json"))):
                dest = building_schemas_dir / schema_path.name
                shutil.copy2(schema_path, dest)
                rel_schema_path = f"schemas/{schema_path.name}"
                with open(dest, "rb") as f:
                    file_manifest_entries[rel_schema_path] = hash_stream(f)

        # Query dynamic source_snapshot from database sources table
        s_cur = conn.cursor()
        s_cur.execute("""
            SELECT DISTINCT s.source_id, s.name, s.authority, s.policy_version, s.access_mode
            FROM sources s
            JOIN artifacts a ON a.source_id = s.source_id
            JOIN versions v ON v.artifact_id = a.artifact_id
            JOIN records r ON r.version_id = v.version_id
            WHERE r.approval_status = 'approved' AND r.validation_status = 'valid'
        """)
        source_rows = s_cur.fetchall()
        source_snapshot = [
            {
                "source_id": row[0],
                "name": row[1],
                "authority": row[2],
                "policy_version": row[3],
                "access_mode": row[4],
            }
            for row in source_rows
        ]
        if not source_snapshot:
            s_cur.execute("SELECT source_id, name, authority, policy_version, access_mode FROM sources WHERE enabled = 1")
            source_snapshot = [
                {
                    "source_id": row[0],
                    "name": row[1],
                    "authority": row[2],
                    "policy_version": row[3],
                    "access_mode": row[4],
                }
                for row in s_cur.fetchall()
            ]

        now_rfc3339 = datetime.now(UTC).isoformat()
        release_meta = {
            "release_id": release_id,
            "release_type": "full",
            "schema_version": "1.0.0",
            "pipeline_version": "0.1.0",
            "created_at": now_rfc3339,
            "published_at": None,
            "counts": counts_dict,
            "source_snapshot": source_snapshot,
            "previous_release_id": None,
        }

        release_file = building_dir / "release.json"
        with open(release_file, "w", encoding="utf-8") as f:
            json.dump(release_meta, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        with open(release_file, "rb") as f:
            file_manifest_entries["release.json"] = hash_stream(f)

        manifest_obj = {
            "algorithm": "sha256",
            "files": file_manifest_entries,
        }
        manifest_file = building_dir / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_obj, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        with open(manifest_file, "rb") as f:
            manifest_sha256 = hash_stream(f)

        # 6. Verify building release package before atomic rename
        verify_release_directory(building_dir, expected_release_id=release_id)

        # 7. Atomic Rename
        os.replace(building_dir, final_dir)

        # 8. Record release and release_items in catalog DB (batch insert)
        create_release(
            conn=conn,
            release_id=release_id,
            release_path=str(Path("releases") / release_id),
            status="verified",
            schema_version="1.0.0",
            counts_json=json.dumps(counts_dict),
            source_snapshot_json=json.dumps(release_meta["source_snapshot"]),
            manifest_sha256=manifest_sha256,
        )

        item_cur = spool_conn.cursor()
        item_cur.execute("SELECT record_id, record_sha256 FROM payload_spool")
        item_batch = []
        while True:
            rows = item_cur.fetchmany(batch_size)
            if not rows:
                break
            for r in rows:
                item_batch.append((release_id, r[0], r[1]))
                if len(item_batch) >= batch_size:
                    conn.executemany(
                        "INSERT INTO release_items (release_id, record_id, record_sha256) VALUES (?, ?, ?)",
                        item_batch,
                    )
                    item_batch.clear()

        if item_batch:
            conn.executemany(
                "INSERT INTO release_items (release_id, record_id, record_sha256) VALUES (?, ?, ?)",
                item_batch,
            )
            item_batch.clear()

        spool_conn.close()
        if spool_db_path.exists():
            try:
                spool_db_path.unlink()
            except OSError:
                pass

        return release_meta

    except Exception as e:
        spool_conn.close()
        if spool_db_path.exists():
            try:
                spool_db_path.unlink()
            except OSError:
                pass
        if building_dir.exists():
            shutil.rmtree(building_dir, ignore_errors=True)
        raise ReleaseBuildError(f"Failed to build release {release_id}: {e}") from e
    finally:
        conn.close()
