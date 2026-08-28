import json

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    insert_artifact,
    migrate,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.pipeline import process_artifact_pipeline


def test_pipeline_cp1254_turkish_encoding_preservation(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "resmi_gazete" / "2026" / "rg-20260826-4" / "hashrg"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    html_content = """<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=Windows-1254">
</head>
<body>
<h1>KONKORDATO GİDER AVANSI TARİFESİ</h1>
<p><b>Madde 9-</b> (1) Bu Tarife yayım tarihinde yürürlüğe girer.</p>
<p>Çalışma, işçi, işveren, değişiklik, tebliğ ve yönetmelik.</p>
</body>
</html>"""
    raw_bytes = html_content.encode("cp1254")
    raw_file.write_bytes(raw_bytes)

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

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
        artifact_id="art-rg-encoding-1",
        document_id="tr:legislation:communique:rg-20260826-4",
        source_id="resmi_gazete",
        source_url="https://www.resmigazete.gov.tr/eskiler/2026/08/20260826-4.htm",
        retrieved_at="2026-08-26T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html; charset=Windows-1254",
        detected_content_type="text/html",
        byte_size=byte_size,
        sha256=sha256,
        raw_path=str(raw_file.relative_to(tmp_path)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json=json.dumps({"source_role": "original_publication", "publication_date": "2026-08-26"}),
    )
    conn.close()

    status = process_artifact_pipeline(artifact_id="art-rg-encoding-1")
    assert status == "needs_review"

    # Verify canonical jsonl content
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT record_id, canonical_path FROM records WHERE record_id = 'tr:legislation:communique:rg-20260826-4:article:9'"
    )
    row = cur.fetchone()
    assert row is not None, "Article record was not created in records table"
    art_record_id, canonical_rel_path = row
    conn.close()

    canonical_file = tmp_path / canonical_rel_path
    assert canonical_file.exists()

    with open(canonical_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]

    article_records = [r for r in lines if r.get("id") == art_record_id]
    assert len(article_records) >= 1
    art_rec = article_records[0]
    art_heading = art_rec.get("heading", "")
    art_text = art_rec.get("text", "")
    full_content = f"{art_heading} {art_text}"

    # Exact Turkish characters must be present
    assert "yayım" in full_content, f"Expected 'yayım' in canonical content, got: {full_content}"
    assert "yürürlüğe" in full_content, f"Expected 'yürürlüğe' in canonical content, got: {full_content}"
    assert "Çalışma" in full_content
    assert "işçi" in full_content
    assert "işveren" in full_content
    assert "değişiklik" in full_content
    assert "tebliğ" in full_content
    assert "yönetmelik" in full_content
    assert "yaym" not in full_content
    assert "yrrle" not in full_content

    # Raw artifact SHA256 must be identical
    with open(raw_file, "rb") as f:
        assert hash_stream(f) == sha256
