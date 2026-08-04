import json
from pathlib import Path

from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream


class ReleaseVerificationError(Exception):
    pass


def verify_release(release_id: str) -> bool:
    """
    Verifies integrity of a release package against its manifest.json.
    """
    settings = load_settings()
    release_dir = settings.data_root_path / "releases" / release_id
    manifest_path = release_dir / "manifest.json"

    if not manifest_path.exists():
        raise ReleaseVerificationError(f"Release manifest.json not found in {release_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    files_dict = manifest.get("files", {})
    for rel_filename, expected_hash in files_dict.items():
        target_file = release_dir / rel_filename
        if not target_file.exists():
            raise ReleaseVerificationError(f"File {rel_filename} missing from release {release_id}")

        with open(target_file, "rb") as f:
            actual_hash = hash_stream(f)

        if actual_hash != expected_hash:
            raise ReleaseVerificationError(
                f"File hash mismatch for {rel_filename} in release {release_id}: expected {expected_hash}, got {actual_hash}"
            )

    return True
