import json
import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    migrate,
)
from mesa_legal_data.web.app import create_app


def test_release_diff_and_package(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    # Setup two releases on disk
    rel1_dir = tmp_path / "releases" / "v1.0.0"
    rel1_dir.mkdir(parents=True, exist_ok=True)
    m1_data = {
        "release_id": "v1.0.0",
        "records": [
            {"id": "rec-1", "sha256": "sha111"},
            {"id": "rec-2", "sha256": "sha222"},
        ],
    }
    (rel1_dir / "manifest.json").write_text(json.dumps(m1_data), encoding="utf-8")

    rel2_dir = tmp_path / "releases" / "v2.0.0"
    rel2_dir.mkdir(parents=True, exist_ok=True)
    m2_data = {
        "release_id": "v2.0.0",
        "records": [
            {"id": "rec-2", "sha256": "sha222_modified"},
            {"id": "rec-3", "sha256": "sha333"},
        ],
    }
    (rel2_dir / "manifest.json").write_text(json.dumps(m2_data), encoding="utf-8")

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO releases (release_id, release_path, status, schema_version, created_at, manifest_sha256, counts_json, source_snapshot_json)
           VALUES ('v1.0.0', 'releases/v1.0.0', 'verified', '1.0.0', '2026-08-05T00:00:00Z', 'm1sha', '{}', '[]')"""
    )
    c.execute(
        """INSERT INTO releases (release_id, release_path, status, schema_version, created_at, manifest_sha256, counts_json, source_snapshot_json)
           VALUES ('v2.0.0', 'releases/v2.0.0', 'verified', '1.0.0', '2026-08-05T00:00:00Z', 'm2sha', '{}', '[]')"""
    )
    conn.commit()
    conn.close()

    app = create_app()
    client = TestClient(app)

    # 1. Release diff
    res_diff = client.get("/api/releases/diff?from=v1.0.0&to=v2.0.0")
    assert res_diff.status_code == 200
    diff_data = res_diff.json()["data"]
    assert diff_data["counts"]["added"] == 1  # rec-3
    assert diff_data["counts"]["removed"] == 1  # rec-1
    assert diff_data["counts"]["modified"] == 1  # rec-2
    assert "rec-3" in diff_data["added_records"]
    assert "rec-1" in diff_data["removed_records"]

    # 2. Release package tar.gz download
    res_pkg = client.get("/api/releases/v1.0.0/package", headers={"X-MESA-Actor": "packager"})
    assert res_pkg.status_code == 200
    assert len(res_pkg.content) > 0
