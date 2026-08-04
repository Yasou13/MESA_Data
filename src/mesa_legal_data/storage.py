import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from mesa_legal_data.config import load_settings


class DuplicateArtifact(Exception):
    pass


class StorageError(Exception):
    pass


def get_tmp_dir() -> Path:
    settings = load_settings()
    return settings.data_root_path / "tmp"


def atomic_write(source_stream: BinaryIO, target_path: Path):
    """
    Writes data from source_stream to target_path atomically.
    If target_path already exists, raises DuplicateArtifact.
    """
    if target_path.exists():
        raise DuplicateArtifact(f"Artifact already exists at {target_path}")

    # Ensure target parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = get_tmp_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    fd, temp_path_str = tempfile.mkstemp(dir=tmp_dir, prefix=".tmp_write_")
    temp_path = Path(temp_path_str)

    try:
        with os.fdopen(fd, "wb") as f:
            # Chunked read to avoid loading large files into memory
            while True:
                chunk = source_stream.read(8192)
                if not chunk:
                    break
                f.write(chunk)

            f.flush()
            os.fsync(f.fileno())

        # Atomic rename (POSIX guarantees atomicity for rename, on Windows os.replace is used under the hood in Path.replace)
        temp_path.replace(target_path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise StorageError(f"Failed to atomically write {target_path}: {e}") from e
