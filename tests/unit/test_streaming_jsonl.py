import json

import pytest


class NoBulkReadWrapper:
    """
    Test wrapper that raises AssertionError if readlines() or full read() is invoked.
    """

    def __init__(self, file_obj):
        self._f = file_obj

    def readlines(self, *args, **kwargs):
        raise AssertionError("Bulk read (readlines) is strictly forbidden")

    def read(self, *args, **kwargs):
        if not args or args[0] in (-1, None):
            raise AssertionError("Full read (read()) is strictly forbidden")
        return self._f.read(*args, **kwargs)

    def __iter__(self):
        return iter(self._f)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._f.close()


def test_nobulkread_wrapper_raises_on_readlines(tmp_path):
    dummy_file = tmp_path / "dummy.jsonl"
    dummy_file.write_text('{"id":"1"}\n{"id":"2"}\n', encoding="utf-8")

    with open(dummy_file, "r", encoding="utf-8") as f:
        wrapper = NoBulkReadWrapper(f)
        with pytest.raises(AssertionError, match="Bulk read"):
            wrapper.readlines()


def test_streaming_line_by_line_iteration(tmp_path):
    dummy_file = tmp_path / "dummy.jsonl"
    dummy_file.write_text('{"id":"1"}\n{"id":"2"}\n', encoding="utf-8")

    lines_read = []
    with open(dummy_file, "r", encoding="utf-8") as f:
        wrapper = NoBulkReadWrapper(f)
        for line in wrapper:
            lines_read.append(line.strip())

    assert len(lines_read) == 2
    assert json.loads(lines_read[0])["id"] == "1"
