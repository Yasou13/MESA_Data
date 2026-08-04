from mesa_legal_data.canonical import compute_record_line_hash, write_canonical_part


def test_canonical_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    records = [
        {"id": "rec-1", "title": "Test 1"},
        {"id": "rec-2", "title": "Test 2"},
    ]

    locs = write_canonical_part(records, "legislation", "run-123", year=2026)
    assert len(locs) == 2
    assert locs[0].record_id == "rec-1"
    assert locs[0].line_number == 1
    assert locs[1].record_id == "rec-2"
    assert locs[1].line_number == 2

    written_file = tmp_path / locs[0].relative_path
    assert written_file.exists()

    with open(written_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 2
        assert compute_record_line_hash(lines[0]) == locs[0].record_sha256
