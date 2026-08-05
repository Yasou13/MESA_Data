from mesa_legal_data.audit import run_doctor_check


def test_doctor_check_corrupted_or_missing_db_disk_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    # Create dummy raw and canonical files
    raw_file = tmp_path / "raw" / "legislation" / "doc1.html"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("<html>test</html>")

    can_file = tmp_path / "canonical" / "legislation" / "doc1.jsonl"
    can_file.parent.mkdir(parents=True, exist_ok=True)
    can_file.write_text("{}")

    # DB file does not exist
    res = run_doctor_check()
    assert res["catalog_sqlite_exists"] is False
    assert res["catalog_sqlite_healthy"] is False
    assert res["recovery_recommended"] is True
    assert len(res["disk_raw_files"]) == 1
    assert len(res["disk_canonical_files"]) == 1

    # DB file exists but corrupted (0-byte file)
    db_file = tmp_path / "catalog.sqlite"
    db_file.write_bytes(b"invalid sqlite data header")

    res_corrupt = run_doctor_check()
    assert res_corrupt["catalog_sqlite_exists"] is True
    assert res_corrupt["catalog_sqlite_healthy"] is False
    assert res_corrupt["recovery_recommended"] is True


def test_doctor_check_release_consistency(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    rel_dir = tmp_path / "releases"
    rel_dir.mkdir(parents=True, exist_ok=True)

    # Stale .building directory
    (rel_dir / "v1.0.0.building").mkdir()

    # .orphaned directory
    (rel_dir / "v0.9.0.orphaned").mkdir()

    res = run_doctor_check()
    assert "v1.0.0.building" in res["stale_building_releases"]
    assert "v0.9.0.orphaned" in res["orphaned_releases"]
