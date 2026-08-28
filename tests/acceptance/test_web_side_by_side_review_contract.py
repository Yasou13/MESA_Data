from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.web.app import create_app


def test_index_html_contains_side_by_side_and_bulk_elements():
    app = create_app()
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # Check modal and bulk review buttons
    assert 'id="modal-record-detail"' in html
    assert 'id="btn-record-approve"' in html
    assert 'id="btn-record-reject"' in html
    assert 'id="btn-version-approve"' in html
    assert 'id="btn-version-reject"' in html
    assert "Belgenin Bu Sürümünü Onayla" in html
    assert "Belgenin Bu Sürümünü Reddet" in html


def test_styles_css_contains_split_view_tokens():
    app = create_app()
    client = TestClient(app)

    res = client.get("/static/styles.css")
    assert res.status_code == 200
    css = res.text

    assert ".review-split-view" in css
    assert ".review-panel" in css
    assert ".review-panel-header" in css
    assert ".review-panel-body" in css
    assert "grid-template-columns: 1fr 1fr" in css


def test_app_js_contains_side_by_side_labels_and_escaping():
    app = create_app()
    client = TestClient(app)

    res = client.get("/static/app.js")
    assert res.status_code == 200
    js = res.text

    assert "Ham Kaynak (HTML)" in js
    assert "Canonical Kayıt" in js
    assert "handleVersionBulkDecision" in js
    assert "btn-version-approve" in js
    assert "btn-version-reject" in js
    assert "escapeHtml" in js


def test_raw_html_endpoint_and_xss_safety(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "resmi_gazete" / "2026" / "rg-xss" / "hashxss"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    # Potentially dangerous XSS payload
    malicious_html = """<html>
<head><meta charset="utf-8"></head>
<body>
<h1>BAŞLIK <script>alert('xss')</script></h1>
<p><b>Madde 1-</b> Güvenlik testi <img src=x onerror=alert(1)>.</p>
</body>
</html>"""
    raw_bytes = malicious_html.encode("utf-8")
    raw_file.write_bytes(raw_bytes)

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)

    conn = get_connection()
    upsert_source(conn, "resmi_gazete", "Resmî Gazete", "T.C. Cumhurbaşkanlığı", "https://www.resmigazete.gov.tr")
    upsert_document(
        conn,
        "tr:legislation:law:9999",
        "legislation",
        "law",
        "TR",
        "Güvenlik Testi Kanunu",
        "9999",
        "fetched",
    )
    insert_artifact(
        conn,
        artifact_id="art-xss-1",
        document_id="tr:legislation:law:9999",
        source_id="resmi_gazete",
        source_url="https://www.resmigazete.gov.tr/9999",
        retrieved_at="2026-08-01T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=len(raw_bytes),
        sha256=sha256,
        raw_path=str(raw_file.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    app = create_app()
    client = TestClient(app)

    res = client.get("/api/documents/tr:legislation:law:9999/text")
    assert res.status_code == 200
    data = res.json()["data"]
    # The API returns raw content string (which the UI escapes with escapeHtml)
    assert "<script>alert('xss')</script>" in data["content"]
    assert data["source_type"] == "raw"
