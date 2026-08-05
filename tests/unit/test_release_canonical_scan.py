import builtins

from mesa_legal_data.catalog import (
    approve_version_with_checks,
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release


def test_canonical_file_opened_only_once_per_part(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    # Generate multi-article payload
    html_lines = ["<!DOCTYPE html><html><body>", "<h1>TÜRK MEDENİ KANUNU</h1>"]
    for i in range(1, 51):
        html_lines.append(f"<p><b>Madde {i}-</b> Test maddesi {i}.</p>")
    html_lines.append("</body></html>")
    html_text = "\n".join(html_lines)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashscan"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"
    raw_file.write_text(html_text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-scan-1",
        document_id="tr:legislation:law:4721",
        source_id="mevzuat",
        source_url="https://www.mevzuat.gov.tr/4721",
        retrieved_at="2026-08-05T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=byte_size,
        sha256=sha256,
        raw_path=str(raw_file.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    process_artifact_pipeline(artifact_id="art-scan-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Approved 50 articles")
    conn.close()

    # Track open calls to canonical JSONL part files
    canonical_open_counts = {}
    original_open = builtins.open

    def tracking_open(file, *args, **kwargs):
        str_file = str(file)
        if "canonical" in str_file and "releases" not in str_file and str_file.endswith(".jsonl"):
            canonical_open_counts[str_file] = canonical_open_counts.get(str_file, 0) + 1
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    rel_meta = build_release(release_id="rel-scan-test")

    assert rel_meta["counts"]["article_count"] == 50

    # Ensure every canonical part file was opened EXACTLY ONCE
    assert len(canonical_open_counts) > 0
    for path, count in canonical_open_counts.items():
        assert count == 1, f"Canonical part file {path} was opened {count} times (expected 1 for O(n) sequential scan)"
