from fastapi.testclient import TestClient

from mesa_legal_data.catalog import get_db_path, migrate
from mesa_legal_data.web.app import create_app


def test_web_e2e_acceptance_flow(tmp_path, monkeypatch):
    """
    Full end-to-end acceptance test for MESA Web Admin API.
    Executes the entire lifecycle via HTTP requests: upload -> process -> review -> build -> verify -> publish -> import -> rollback -> provenance.
    """
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    staging_db = tmp_path / "data" / "mesa_staging.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(staging_db))

    db_path = get_db_path()
    migrate(None, db_path)

    app = create_app()
    client = TestClient(app)

    # 1. Dashboard Check (Empty)
    res_dash0 = client.get("/api/dashboard")
    assert res_dash0.status_code == 200
    assert res_dash0.json()["data"]["counts"]["documents"] == 0

    # 2. Upload Synthetic Law HTML File
    law_text = (
        "<!DOCTYPE html><html><body>\n"
        "<h1>TÜRK MEDENİ KANUNU</h1>\n"
        "<p><b>Madde 1-</b> Kanun, sözüyle ve özüyle değindiği bütün konularda uygulanır.</p>\n"
        "<p><b>Madde 2-</b> Herkes, haklarını kullanırken dürüstlük kurallarına uymak zorundadır.</p>\n"
        "</body></html>"
    )

    res_up = client.post(
        "/api/artifacts/upload",
        data={
            "source_id": "mevzuat",
            "document_id": "tr:legislation:law:4721",
            "family": "legislation",
            "document_type": "law",
            "title": "Türk Medeni Kanunu",
        },
        files={"file": ("payload.html", law_text.encode("utf-8"), "text/html")},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_up.status_code == 200
    art_id = res_up.json()["data"]["artifact_id"]

    # 3. Process Artifact Pipeline
    res_proc = client.post(
        f"/api/artifacts/{art_id}/process",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_proc.status_code == 200
    assert res_proc.json()["data"]["pipeline_status"] == "needs_review"

    # 4. List Pending Records
    res_recs = client.get("/api/records?approval_status=pending")
    assert res_recs.status_code == 200
    records = res_recs.json()["data"]["items"]
    assert len(records) >= 1

    ver_id = records[0]["version_id"]

    # 5. Approve Version
    res_app = client.post(
        f"/api/versions/{ver_id}/approve",
        json={"reviewer": "yasin_web", "note": "Web E2E Approved"},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_app.status_code == 200

    # 6. Build Release
    rel1 = "rel-web-e2e-1"
    res_build = client.post(
        "/api/releases",
        json={"release_id": rel1},
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_build.status_code == 200
    assert res_build.json()["data"]["counts"]["legislation_count"] == 1
    assert res_build.json()["data"]["counts"]["article_count"] == 2

    # 7. Verify Release
    res_ver = client.post(
        f"/api/releases/{rel1}/verify",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_ver.status_code == 200
    assert res_ver.json()["data"]["verified"] is True

    # 8. Publish Release
    res_pub = client.post(
        f"/api/releases/{rel1}/publish",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_pub.status_code == 200

    # 9. Import Release to MESA Staging DB
    res_imp = client.post(
        f"/api/releases/{rel1}/import",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_imp.status_code == 200
    assert res_imp.json()["data"]["status"] == "imported"

    # 10. Dashboard Active Release Check
    res_dash1 = client.get("/api/dashboard")
    assert res_dash1.status_code == 200
    assert res_dash1.json()["data"]["counts"]["active_release_id"] == rel1

    # 11. Provenance Check
    res_prov = client.get("/api/provenance/tr:legislation:law:4721")
    assert res_prov.status_code == 200
    assert res_prov.json()["data"]["active_release_id"] == rel1

    # 12. Build & Import Second Release, then Rollback
    rel2 = "rel-web-e2e-2"
    client.post("/api/releases", json={"release_id": rel2}, headers={"X-MESA-Requested-With": "web-admin"})
    client.post(f"/api/releases/{rel2}/publish", headers={"X-MESA-Requested-With": "web-admin"})
    client.post(f"/api/releases/{rel2}/import", headers={"X-MESA-Requested-With": "web-admin"})

    res_dash2 = client.get("/api/dashboard")
    assert res_dash2.json()["data"]["counts"]["active_release_id"] == rel2

    res_roll = client.post(
        f"/api/releases/{rel1}/rollback",
        headers={"X-MESA-Requested-With": "web-admin"},
    )
    assert res_roll.status_code == 200
    assert res_roll.json()["data"]["active_release_id"] == rel1

    res_dash3 = client.get("/api/dashboard")
    assert res_dash3.json()["data"]["counts"]["active_release_id"] == rel1
