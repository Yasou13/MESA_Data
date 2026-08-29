import hashlib
import json
from pathlib import Path

from mesa_legal_data.catalog import get_connection as get_catalog_connection
from mesa_legal_data.catalog import get_release
from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.release.security import validate_release_id
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

    # 1. Verify path traversal safety and SHA256 hashes for all manifested files
    for rel_filename, expected_hash in files_dict.items():
        if rel_filename.startswith("/") or ".." in rel_filename or "\\" in rel_filename:
            raise ReleaseVerificationError(f"Path traversal detected in manifest filename: {rel_filename}")

        target_file = release_dir / rel_filename
        if target_file.is_symlink():
            raise ReleaseVerificationError(f"Symlink files are forbidden in release: {rel_filename}")

        if not target_file.exists():
            raise ReleaseVerificationError(f"File {rel_filename} missing from release directory {release_dir}")

        with open(target_file, "rb") as f:
            actual_hash = hash_stream(f)

        if actual_hash.lower() != expected_hash.lower():
            raise ReleaseVerificationError(
                f"File hash mismatch for {rel_filename}: expected {expected_hash}, got {actual_hash}"
            )

    # 2. Reject unmanifested files and symlinks inside the release directory tree
    manifested_set = set(files_dict.keys())
    manifested_set.add("manifest.json")

    for entry in release_dir.rglob("*"):
        if entry.is_symlink():
            raise ReleaseVerificationError(f"Symlink detected in release directory: {entry}")
        if entry.is_file():
            rel_p = entry.relative_to(release_dir).as_posix()
            if rel_p not in manifested_set:
                raise ReleaseVerificationError(f"Unmanifested file found in release package: {rel_p}")

    # 3. Verify release.json details and line counts
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
    payload_identities: dict[str, tuple[str, str]] = {}

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
                payload_identities[r_id] = (r_type, hashlib.sha256(line.encode("utf-8")).hexdigest())

        if actual_count != expected_count:
            raise ReleaseVerificationError(
                f"Count mismatch in {rel_path}: expected {expected_count}, found {actual_count} lines"
            )

    # The release-owned identity index binds every payload to its exact legal
    # version and document. Publisher planning consumes this verified file,
    # never a reconstructed live-catalog join.
    index_path = release_dir / "data/release-index.jsonl"
    if not index_path.exists():
        # Legacy release packages predate publisher-bound version identity.
        # They remain verifiable for local archival/import, but the MESA
        # publisher rejects them because it requires this frozen index.
        return True

    indexed_ids: set[str] = set()
    indexed_instances: set[tuple[str, str]] = set()
    with open(index_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            try:
                item = json.loads(line)
                record_id = item["record_id"]
                record_type = item["record_type"]
                record_sha256 = item["record_sha256"]
                payload_sha256 = item["payload_sha256"]
                version_id = item["version_id"]
                document_id = item["document_id"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ReleaseVerificationError(f"Invalid release index entry at line {idx}: {exc}") from exc
            if not all(
                isinstance(value, str) and value
                for value in (record_id, record_type, record_sha256, payload_sha256, version_id, document_id)
            ):
                raise ReleaseVerificationError(f"Empty or non-string release index identity at line {idx}")
            if record_id in indexed_ids or (version_id, record_id) in indexed_instances:
                raise ReleaseVerificationError(
                    f"Duplicate release index identity at line {idx}: {version_id}/{record_id}"
                )
            expected_payload = payload_identities.get(record_id)
            if expected_payload != (record_type, payload_sha256):
                raise ReleaseVerificationError(f"Release index does not match payload for record '{record_id}'")
            indexed_ids.add(record_id)
            indexed_instances.add((version_id, record_id))

    if indexed_ids != seen_record_ids:
        raise ReleaseVerificationError("Release index membership does not exactly match packaged payloads")

    return True


def verify_release(release_id: str) -> bool:
    """
    Verifies integrity of a published release package against catalog manifest_sha256 trust anchor.
    """
    validate_release_id(release_id)

    settings = load_settings()
    release_dir = settings.data_root_path / "releases" / release_id
    if not release_dir.exists():
        raise ReleaseVerificationError(f"Release directory not found: {release_dir}")

    manifest_path = release_dir / "manifest.json"
    if not manifest_path.exists():
        raise ReleaseVerificationError(f"Release manifest.json missing from {release_dir}")

    with open(manifest_path, "rb") as f:
        actual_manifest_sha256 = hash_stream(f)

    conn = get_catalog_connection()
    try:
        rel = get_release(conn, release_id)
        if not rel:
            raise ReleaseVerificationError(f"Release '{release_id}' not found in catalog database")
        catalog_manifest_sha256 = rel.get("manifest_sha256")
        if not catalog_manifest_sha256:
            raise ReleaseVerificationError(f"Catalog release '{release_id}' has no recorded manifest_sha256")
        if actual_manifest_sha256.lower() != catalog_manifest_sha256.lower():
            raise ReleaseVerificationError(
                f"Release manifest SHA256 mismatch with catalog trust anchor: expected {catalog_manifest_sha256}, got {actual_manifest_sha256}"
            )
    finally:
        conn.close()

    return verify_release_directory(release_dir, expected_release_id=release_id)
