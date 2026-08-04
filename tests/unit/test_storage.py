import io

import pytest

from mesa_legal_data.storage import DuplicateArtifact, atomic_write


def test_atomic_write(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    target = tmp_path / "target.txt"
    content = b"Atomic content"
    stream = io.BytesIO(content)

    atomic_write(stream, target)

    assert target.exists()
    assert target.read_bytes() == content

    # Test duplicate
    stream2 = io.BytesIO(b"New content")
    with pytest.raises(DuplicateArtifact):
        atomic_write(stream2, target)

    # Original content should remain untouched
    assert target.read_bytes() == content


def test_atomic_write_creates_parents(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    target = tmp_path / "deep" / "dir" / "file.txt"

    atomic_write(io.BytesIO(b"Data"), target)

    assert target.exists()
    assert target.read_bytes() == b"Data"
