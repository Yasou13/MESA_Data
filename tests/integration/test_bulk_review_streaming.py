import builtins
import hashlib

import pytest

from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.pipeline import process_artifact_pipeline


@pytest.mark.scale
def test_bulk_review_streaming_scale_and_single_pass(tmp_path, monkeypatch):

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    # 1. Create multi-article document payload (10,000 articles)
    html_lines = ["<!DOCTYPE html><html><body>", "<h1>TÜRK MEDENİ KANUNU</h1>"]
    for i in range(1, 10001):
        html_lines.append(f"<p><b>Madde {i}-</b> Test maddesi {i}.</p>")
    html_lines.append("</body></html>")
    raw_content = "\n".join(html_lines)
    raw_bytes = raw_content.encode("utf-8")
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashbulk"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"
    raw_file.write_bytes(raw_bytes)

    conn = get_connection()
    upsert_source(conn, "mevzuat", "Mevzuat", "T.C. Cumhurbaşkanlığı", "https://www.mevzuat.gov.tr")
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")
    insert_artifact(
        conn,
        "art-bulk-10k",
        "tr:legislation:law:4721",
        "mevzuat",
        "https://www.mevzuat.gov.tr/4721",
        "2026-08-05T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(raw_bytes),
        actual_sha256,
        str(raw_file.relative_to(tmp_path)),
        None,
        None,
        "fetched",
        None,
        "{}",
    )
    conn.close()

    run_id = process_artifact_pipeline(artifact_id="art-bulk-10k")
    assert isinstance(run_id, str)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT version_id FROM versions LIMIT 1")
    row = cur.fetchone()
    assert row is not None, "No version created by pipeline"
    ver_id = row[0]
    conn.close()

    # Track open calls on canonical part files
    canonical_open_counts = {}
    original_open = builtins.open

    def tracking_open(file, *args, **kwargs):
        str_file = str(file)
        if "canonical" in str_file and "releases" not in str_file and str_file.endswith(".jsonl"):
            canonical_open_counts[str_file] = canonical_open_counts.get(str_file, 0) + 1
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    conn = get_connection()
    res = approve_version_streaming(conn, version_id=ver_id, reviewer="reviewer_bulk", note="Bulk approval")
    conn.close()

    assert res["approved_records"] >= 10000

    # Ensure canonical file was opened EXACTLY ONCE
    assert len(canonical_open_counts) > 0
    for path, count in canonical_open_counts.items():
        assert count == 1, f"Canonical part file {path} was opened {count} times (expected 1 for O(n) streaming scan)"

    # Verify DB states
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM record_reviews WHERE reviewer = 'reviewer_bulk'")
    assert cur.fetchone()[0] >= 10000

    cur.execute("SELECT approval_status FROM versions WHERE version_id = ?", (ver_id,))
    assert cur.fetchone()[0] == "approved"
    conn.close()
