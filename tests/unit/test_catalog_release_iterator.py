from mesa_legal_data.catalog import (
    ReleaseRecordRef,
    approve_version_with_checks,
    get_connection,
    get_db_path,
    insert_artifact,
    iter_records_for_release,
    migrate,
    upsert_document,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline


class NoFetchallCursor:
    def __init__(self, cursor):
        self._cur = cursor

    def fetchall(self, *args, **kwargs):
        raise AssertionError("cursor.fetchall() is strictly forbidden in release selection")

    def __getattr__(self, name):
        return getattr(self._cur, name)


class NoFetchallConnection:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *args, **kwargs):
        cur = self._conn.cursor(*args, **kwargs)
        return NoFetchallCursor(cur)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_catalog_release_iterator_no_fetchall(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashiter"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"
    raw_file.write_text(
        "<!DOCTYPE html><html><body><h1>TÜRK MEDENİ KANUNU</h1><p><b>Madde 1-</b> Kanun uygulanır.</p></body></html>",
        encoding="utf-8",
    )

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-iter-1",
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

    process_artifact_pipeline(artifact_id="art-iter-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Approved")
    conn.close()

    conn = get_connection()
    wrapped_conn = NoFetchallConnection(conn)
    records = list(iter_records_for_release(wrapped_conn, batch_size=2))
    conn.close()

    assert len(records) >= 2
    assert all(isinstance(r, ReleaseRecordRef) for r in records)
