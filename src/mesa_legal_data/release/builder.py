import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mesa_legal_data.catalog import (
    add_release_item,
    create_release,
    get_connection,
    list_open_blocking_issues,
    list_records_for_release,
)
from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.schema_validation import validate_record


class ReleaseBuildError(Exception):
    pass


def build_release(release_id: str | None = None) -> dict[str, Any]:
    """
    Builds a release package from approved canonical records.
    Uses temporary .building-* directory and verifies integrity before atomic finalize.
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

    try:
        # Check open blocker issues
        blockers = list_open_blocking_issues(conn)
        if blockers:
            raise ReleaseBuildError(f"Cannot build release: open blocker issues exist: {blockers}")

        eligible_records = list_records_for_release(conn)

        # Categorize records
        records_by_type: dict[str, list[dict[str, Any]]] = {
            "legislation": [],
            "article": [],
            "decision": [],
            "citation": [],
        }
        release_items_meta: list[tuple[str, str]] = []

        for r_meta in eligible_records:
            r_id = r_meta["record_id"]
            r_type = r_meta["record_type"]
            c_rel_path = r_meta["canonical_path"]
            c_line_num = r_meta["canonical_line"]
            expected_hash = r_meta["record_sha256"]

            c_abs_path = data_root / c_rel_path
            if not c_abs_path.exists():
                raise ReleaseBuildError(f"Canonical file missing for record {r_id}: {c_abs_path}")

            line_str = None
            with open(c_abs_path, "r", encoding="utf-8") as f:
                for current_idx, line in enumerate(f, start=1):
                    if current_idx == c_line_num:
                        line_str = line
                        break

            if line_str is None:
                raise ReleaseBuildError(f"Line number {c_line_num} out of bounds in {c_abs_path}")

            actual_hash = hashlib.sha256(line_str.encode("utf-8")).hexdigest()
            if actual_hash.lower() != expected_hash.lower():
                raise ReleaseBuildError(f"Record hash mismatch for {r_id}: expected {expected_hash}, got {actual_hash}")

            rec_obj = json.loads(line_str)
            validate_record(rec_obj)

            if r_type in records_by_type:
                records_by_type[r_type].append(rec_obj)
                release_items_meta.append((r_id, expected_hash))

        counts_dict = {
            "legislation_count": len(records_by_type["legislation"]),
            "article_count": len(records_by_type["article"]),
            "decision_count": len(records_by_type["decision"]),
            "citation_count": len(records_by_type["citation"]),
        }

        # Write data JSONL files
        file_manifest_entries: dict[str, str] = {}

        type_to_filename = {
            "legislation": "data/legislation.jsonl",
            "article": "data/articles.jsonl",
            "decision": "data/decisions.jsonl",
            "citation": "data/citations.jsonl",
        }

        for r_type, r_list in records_by_type.items():
            fn = type_to_filename[r_type]
            out_file = building_dir / fn
            r_list_sorted = sorted(r_list, key=lambda x: x["id"])

            with open(out_file, "w", encoding="utf-8") as f:
                for r in r_list_sorted:
                    line = json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    f.write(line)
                f.flush()
                os.fsync(f.fileno())

            with open(out_file, "rb") as f:
                file_manifest_entries[fn] = hash_stream(f)

        # Copy schema files
        project_schemas_dir = Path(__file__).parent.parent.parent.parent / "schemas"
        if project_schemas_dir.exists():
            for schema_path in project_schemas_dir.glob("*.schema.json"):
                dest = building_schemas_dir / schema_path.name
                shutil.copy2(schema_path, dest)
                rel_schema_path = f"schemas/{schema_path.name}"
                with open(dest, "rb") as f:
                    file_manifest_entries[rel_schema_path] = hash_stream(f)

        now_rfc3339 = datetime.now(UTC).isoformat()
        release_meta = {
            "release_id": release_id,
            "release_type": "full",
            "schema_version": "1.0.0",
            "pipeline_version": "0.1.0",
            "created_at": now_rfc3339,
            "published_at": None,
            "counts": counts_dict,
            "source_snapshot": [
                {
                    "source_id": "mevzuat",
                    "policy_version": "1.0.0",
                    "latest_retrieved_at": now_rfc3339,
                }
            ],
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

        # Atomic Rename
        os.replace(building_dir, final_dir)

        # Record release in catalog
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

        for r_id, r_hash in release_items_meta:
            add_release_item(conn, release_id, r_id, r_hash)

        return release_meta

    except Exception as e:
        if building_dir.exists():
            shutil.rmtree(building_dir, ignore_errors=True)
        raise ReleaseBuildError(f"Failed to build release {release_id}: {e}") from e
    finally:
        conn.close()
