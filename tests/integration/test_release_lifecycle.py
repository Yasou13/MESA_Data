from fastapi.testclient import TestClient

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
from mesa_legal_data.web.app import create_app


def test_release_lifecycle_transitions(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(tmp_path / "mesa_staging.sqlite"))

    db_path = get_db_path()
    migrate(None, db_path)

    raw_dir = tmp_path / "raw" / "legislation" / "mevzuat" / "2026" / "law4721" / "hashlc"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "payload.html"

    text = "<!DOCTYPE html><html><body>\n<h1>TÜRK MEDENİ KANUNU</h1>\n<p><b>Madde 1-</b> Kanun uygulanır.</p>\n</body></html>"
    raw_file.write_text(text, encoding="utf-8")

    with open(raw_file, "rb") as f:
        sha256 = hash_stream(f)
    byte_size = raw_file.stat().st_size

    conn = get_connection()
    upsert_document(conn, "tr:legislation:law:4721", "legislation", "law", "TR", "TMK", "4721", "fetched")
    insert_artifact(
        conn,
        artifact_id="art-lc-1",
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

    process_artifact_pipeline(artifact_id="art-lc-1")

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="yasin", note="Approved")
    conn.close()

    app = create_app()
    client = TestClient(app)

    rel_id = "rel-lc-1"

    # Build (creates 'verified' status in catalog)
    res_b = client.post("/api/releases", json={"release_id": rel_id}, headers={"X-MESA-Requested-With": "web-admin"})
    assert res_b.status_code == 200

    # Cannot import 'verified' release
    res_imp0 = client.post(f"/api/releases/{rel_id}/import", headers={"X-MESA-Requested-With": "web-admin"})
    assert res_imp0.status_code == 409

    # Publish
    res_pub = client.post(f"/api/releases/{rel_id}/publish", headers={"X-MESA-Requested-With": "web-admin"})
    assert res_pub.status_code == 200, f"Error: {res_pub.json()}"

    # Cannot publish already published release (status is not 'verified')
    res_pub_again = client.post(f"/api/releases/{rel_id}/publish", headers={"X-MESA-Requested-With": "web-admin"})
    assert res_pub_again.status_code == 409

    # Import published release succeeds
    res_imp1 = client.post(f"/api/releases/{rel_id}/import", headers={"X-MESA-Requested-With": "web-admin"})
    assert res_imp1.status_code == 200

    # Revoke release
    res_rev = client.post(
        f"/api/releases/{rel_id}/revoke",
        json={"reason": "Revoked for testing"},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_rev.status_code == 200

    # Cannot import revoked release
    res_imp2 = client.post(f"/api/releases/{rel_id}/import", headers={"X-MESA-Requested-With": "web-admin"})
    assert res_imp2.status_code == 409
