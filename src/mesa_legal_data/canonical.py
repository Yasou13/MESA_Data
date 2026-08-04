import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mesa_legal_data.config import load_settings


class CanonicalLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: str
    record_type: str
    relative_path: str
    line_number: int
    record_sha256: str


def compute_record_line_hash(record_json_line: str) -> str:
    """
    Computes SHA-256 hash of a single JSONL line (including trailing newline).
    """
    if not record_json_line.endswith("\n"):
        record_json_line += "\n"
    return hashlib.sha256(record_json_line.encode("utf-8")).hexdigest()


def write_canonical_part(
    records: list[dict[str, Any]],
    record_type: str,
    run_id: str,
    year: int | None = None,
) -> list[CanonicalLocation]:
    """
    Writes canonical records deterministically to an immutable JSONL part file.
    Uses atomic write (temp -> fsync -> rename).
    """
    if not records:
        return []

    if year is None:
        year = datetime.now(UTC).year

    settings = load_settings()
    data_root = settings.data_root_path

    rel_dir = Path("canonical") / record_type / f"year={year}"
    target_dir = data_root / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    part_filename = f"part-{run_id}.jsonl"
    final_path = target_dir / part_filename
    rel_file_path = rel_dir / part_filename

    tmp_dir = data_root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = tmp_dir / f"canonical-{run_id}-{record_type}.tmp"

    locations: list[CanonicalLocation] = []

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            for idx, rec in enumerate(records, start=1):
                rec_id = rec["id"]
                # Deterministic JSON encoding
                json_str = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                line = json_str + "\n"
                f.write(line)

                rec_hash = compute_record_line_hash(line)
                locations.append(
                    CanonicalLocation(
                        record_id=rec_id,
                        record_type=record_type,
                        relative_path=str(rel_file_path),
                        line_number=idx,
                        record_sha256=rec_hash,
                    )
                )

            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, final_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    return locations
