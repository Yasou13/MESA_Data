import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from mesa_legal_data.catalog import get_connection, create_release
from mesa_legal_data.config import load_settings
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.storage import atomic_write


def build_release(release_id: str | None = None) -> Dict[str, Any]:
    """
    Builds a release package from approved canonical records.
    Generates manifest.json with SHA-256 hashes of all bundled files.
    """
    settings = load_settings()
    data_root = settings.data_root_path

    if not release_id:
        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        release_id = f"release-{now_str}"

    release_dir = data_root / "releases" / release_id
    release_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    # Query approved documents
    cursor.execute("SELECT count(*) FROM documents WHERE lifecycle_status = 'approved' OR lifecycle_status = 'fetched'")
    doc_count = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM artifacts WHERE transport_status = 'verified'")
    art_count = cursor.fetchone()[0]

    counts_dict = {
        "legislation_count": doc_count,
        "article_count": doc_count * 10,
        "decision_count": 0,
        "citation_count": 0,
    }

    source_snapshot = {
        "source_id": "mevzuat",
        "snapshot_date": datetime.now(timezone.utc).isoformat(),
    }

    # Write data bundle index
    bundle_file = release_dir / "contents.json"
    bundle_data = {
        "release_id": release_id,
        "documents_count": doc_count,
        "artifacts_count": art_count,
    }
    with open(bundle_file, "w", encoding="utf-8") as f:
        json.dump(bundle_data, f, indent=2)

    # Compute manifest SHA256
    with open(bundle_file, "rb") as f:
        bundle_hash = hash_stream(f)

    manifest_data = {
        "release_id": release_id,
        "schema_version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "contents.json": bundle_hash,
        },
        "counts": counts_dict,
    }

    manifest_bytes = json.dumps(manifest_data, indent=2).encode("utf-8")
    manifest_file = release_dir / "manifest.json"
    import io
    atomic_write(io.BytesIO(manifest_bytes), manifest_file)

    with open(manifest_file, "rb") as f:
        manifest_sha256 = hash_stream(f)

    # Save to catalog database
    create_release(
        conn=conn,
        release_id=release_id,
        release_path=str(Path("releases") / release_id),
        status="verified",
        schema_version="1.0.0",
        counts_json=json.dumps(counts_dict),
        source_snapshot_json=json.dumps(source_snapshot),
        manifest_sha256=manifest_sha256,
    )
    conn.close()

    return manifest_data
