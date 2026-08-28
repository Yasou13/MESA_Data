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


def test_web_document_text_cp1254_encoding(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "resmi_gazete" / "2026" / "rg-20260826-4" / "hashwebenc"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    html_content = """<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=Windows-1254">
</head>
<body>
<h1>KONKORDATO GİDER AVANSI TARİFESİ</h1>
<p>Madde 9- (1) Bu Tarife yayım tarihinde yürürlüğe girer.</p>
</body>
</html>"""
    raw_bytes = html_content.encode("cp1254")
    raw_file.write_bytes(raw_bytes)

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)

    conn = get_connection()
    upsert_source(conn, "resmi_gazete", "Resmî Gazete", "T.C. Cumhurbaşkanlığı", "https://www.resmigazete.gov.tr")
    upsert_document(
        conn,
        "tr:legislation:communique:rg-20260826-4",
        "legislation",
        "communique",
        "TR",
        "Konkordato Gider Avansı Tarifesi",
        "20260826-4",
        "fetched",
    )
    insert_artifact(
        conn,
        artifact_id="art-web-enc-1",
        document_id="tr:legislation:communique:rg-20260826-4",
        source_id="resmi_gazete",
        source_url="https://www.resmigazete.gov.tr/eskiler/2026/08/20260826-4.htm",
        retrieved_at="2026-08-26T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html; charset=Windows-1254",
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

    res = client.get("/api/documents/tr:legislation:communique:rg-20260826-4/text")
    assert res.status_code == 200
    data = res.json()["data"]

    content = data["content"]
    assert "yayım" in content, f"Expected 'yayım' in web raw text, got: {content}"
    assert "yürürlüğe" in content, f"Expected 'yürürlüğe' in web raw text, got: {content}"
    assert "yaym" not in content
    assert "yrrle" not in content
    assert data.get("charset") in ("windows-1254", "cp1254")
