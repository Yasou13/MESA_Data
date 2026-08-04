import json
from pathlib import Path

from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.schema_validation import validate_record


class ReleaseVerificationError(Exception):
    pass


def verify_release_directory(release_dir: Path, expected_release_id: str | None = None) -> bool:
    """
    Verifies full integrity of a release directory (works on both .building-* and final releases/{release_id}).
    """
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.exists():
        raise ReleaseVerificationError(f"Release manifest.json not found in {release_dir}")

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        raise ReleaseVerificationError(f"Failed to parse manifest.json: {e}") from e

    files_dict = manifest.get("files", {})
    if not files_dict:
        raise ReleaseVerificationError("manifest.json has no 'files' dictionary")

    # 1. Verify path traversal safety and SHA256 hashes for all files
    for rel_filename, expected_hash in files_dict.items():
        if rel_filename.startswith("/") or ".." in rel_filename:
            raise ReleaseVerificationError(f"Path traversal detected in manifest filename: {rel_filename}")

        target_file = release_dir / rel_filename
        if not target_file.exists():
            raise ReleaseVerificationError(f"File {rel_filename} missing from release directory {release_dir}")

        if target_file.is_symlink():
            raise ReleaseVerificationError(f"Symlink files are forbidden in release: {rel_filename}")

        with open(target_file, "rb") as f:
            actual_hash = hash_stream(f)

        if actual_hash.lower() != expected_hash.lower():
            raise ReleaseVerificationError(
                f"File hash mismatch for {rel_filename}: expected {expected_hash}, got {actual_hash}"
            )

    # 2. Verify release.json details and line counts
    release_json_path = release_dir / "release.json"
    if not release_json_path.exists():
        raise ReleaseVerificationError("release.json missing from release directory")

    with open(release_json_path, "r", encoding="utf-8") as f:
        release_meta = json.load(f)

    meta_rel_id = release_meta.get("release_id")
    if expected_release_id and meta_rel_id != expected_release_id:
        raise ReleaseVerificationError(
            f"Release ID mismatch: expected '{expected_release_id}', got '{meta_rel_id}' in release.json"
        )

    counts = release_meta.get("counts", {})
    type_to_file = {
        "legislation": ("data/legislation.jsonl", counts.get("legislation_count", 0)),
        "article": ("data/articles.jsonl", counts.get("article_count", 0)),
        "decision": ("data/decisions.jsonl", counts.get("decision_count", 0)),
        "citation": ("data/citations.jsonl", counts.get("citation_count", 0)),
    }

    seen_record_ids: set[str] = set()

    for r_type, (rel_path, expected_count) in type_to_file.items():
        jsonl_path = release_dir / rel_path
        if not jsonl_path.exists():
            if expected_count > 0:
                raise ReleaseVerificationError(
                    f"Expected {expected_count} {r_type} records, but {rel_path} does not exist"
                )
            continue

        actual_count = 0
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f, start=1):
                line_str = line.strip()
                if not line_str:
                    continue
                actual_count += 1
                try:
                    rec_obj = json.loads(line_str)
                except Exception as e:
                    raise ReleaseVerificationError(f"Invalid JSON at line {idx} in {rel_path}: {e}") from e

                # Validate record schema
                validate_record(rec_obj)

                r_id = rec_obj.get("id")
                if r_id in seen_record_ids:
                    raise ReleaseVerificationError(f"Duplicate record ID '{r_id}' found in release in {rel_path}")
                seen_record_ids.add(r_id)

        if actual_count != expected_count:
            raise ReleaseVerificationError(
                f"Count mismatch in {rel_path}: expected {expected_count}, found {actual_count} lines"
            )

    return True


def verify_release(release_id: str) -> bool:
    """
    Verifies integrity of a published release package against its manifest.json.
    """
    settings = load_settings()
    release_dir = settings.data_root_path / "releases" / release_id
    if not release_dir.exists():
        raise ReleaseVerificationError(f"Release directory not found: {release_dir}")

    return verify_release_directory(release_dir, expected_release_id=release_id)
