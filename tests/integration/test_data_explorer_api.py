from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    migrate,
)
from mesa_legal_data.web.app import create_app


def test_data_explorer_search_and_facets(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc-ex-1', 'legislation', 'law', 'TR', 'Borçlar Kanunu', 'key-ex-1', 'fetched', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art-ex-1', 'doc-ex-1', 'mevzuat', 'https://example.com/ex1.html', '2026-08-05T00:00:00Z', 'manual', 200, 'text/html', 'text/html', 10, 'sha-ex-1', 'raw/ex1.html', 'fetched', '{}')"""
    )
    c.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
           VALUES ('ver-ex-1', 'doc-ex-1', 'art-ex-1', 'snapshot', 'canonical/ex1.jsonl', 1, 'sha-ver-ex-1', 'test_parser', '1.0', '1.0', 'valid', 'clean', 'approved', '2026-08-05T00:00:00Z')"""
    )
    c.execute(
        """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('rec-ex-1', 'ver-ex-1', 'article', 'canonical/ex1.jsonl', 1, 'sha-rec-ex-1', 'valid', 'approved', '2026-08-05T00:00:00Z')"""
    )
    conn.commit()
    conn.close()

    app = create_app()
    client = TestClient(app)

    # 1. Search endpoint
    res_search = client.get("/api/explorer/search?q=Bor%C3%A7lar&record_type=article")
    assert res_search.status_code == 200
    data_search = res_search.json()["data"]
    assert data_search["total"] == 1
    assert data_search["items"][0]["record_id"] == "rec-ex-1"

    # 2. Facets endpoint
    res_facets = client.get("/api/explorer/facets")
    assert res_facets.status_code == 200
    data_facets = res_facets.json()["data"]
    assert "record_types" in data_facets
    assert data_facets["record_types"].get("article") == 1
    assert data_facets["sources"].get("mevzuat") == 1
