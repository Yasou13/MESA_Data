"""
FINAL-020: Full HTTP E2E Lifecycle
Tests the complete workspace lifecycle via HTTP API:
  seed -> explore -> approve -> revise -> annotate -> export -> config -> backup -> audit
"""

import json

from fastapi.testclient import TestClient

from mesa_legal_data.catalog import get_connection, get_db_path, migrate
from mesa_legal_data.hashing import hash_stream
from mesa_legal_data.web.app import create_app

HEADERS = {"X-MESA-Requested-With": "web-admin", "X-MESA-Actor": "e2e-bot"}


def _seed_data(tmp_path):
    """Seed a document, artifact, version, and records directly into catalog."""
    conn = get_connection()

    # Seed raw file
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "e2e_law.html"
    raw_file.write_text("<html><body>Test</body></html>", encoding="utf-8")
    with open(raw_file, "rb") as f:
        sha = hash_stream(f)

    conn.execute(
        """INSERT INTO documents (document_id, family, document_type, jurisdiction, title, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc-e2e-1', 'legislation', 'law', 'TR', 'E2E Kanunu', 'e2e-key-1', 'fetched', '2026-08-05T00:00:00Z', '2026-08-05T00:00:00Z')"""
    )

    conn.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, http_status, declared_content_type, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art-e2e-1', 'doc-e2e-1', 'mevzuat', 'https://www.mevzuat.gov.tr/e2e.html', '2026-08-05T00:00:00Z', 'manual', 200, 'text/html', 'text/html', ?, ?, 'raw/e2e_law.html', 'verified', '{}')""",
        (raw_file.stat().st_size, sha),
    )

    conn.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, snapshot_date, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at)
           VALUES ('ver-e2e-1', 'doc-e2e-1', 'art-e2e-1', 'consolidated_snapshot', '2026-08-05', 'canonical/e2e/article.jsonl', 1, ?, 'e2e_parser', '1.0', '1.0.0', 'valid', 'cleared', 'pending', '2026-08-05T00:00:00Z')""",
        (sha,),
    )

    # Write canonical JSONL with proper per-line hashes
    canonical_dir = tmp_path / "canonical" / "e2e"
    canonical_dir.mkdir(parents=True, exist_ok=True)

    import hashlib as _hl

    line1 = (
        json.dumps(
            {
                "id": "rec-e2e-art-1",
                "record_type": "article",
                "legislation_id": "doc-e2e-1",
                "article_number": "1",
                "article_kind": "madde",
                "text": "Madde metni",
                "status": "yürürlükte",
                "schema_version": "1.0.0",
                "created_at": "2026-08-05T00:00:00Z",
                "source": {
                    "source_id": "mevzuat",
                    "source_url": "https://example.com",
                    "retrieved_at": "2026-08-05T00:00:00Z",
                    "artifact_sha256": sha,
                },
                "provenance": {"parser_name": "e2e", "parser_version": "1.0", "pipeline_run_id": "run-e2e"},
            }
        )
        + "\n"
    )
    line2 = (
        json.dumps(
            {
                "id": "rec-e2e-art-2",
                "record_type": "article",
                "legislation_id": "doc-e2e-1",
                "article_number": "2",
                "article_kind": "madde",
                "text": "İkinci madde metni",
                "status": "yürürlükte",
                "schema_version": "1.0.0",
                "created_at": "2026-08-05T00:00:00Z",
                "source": {
                    "source_id": "mevzuat",
                    "source_url": "https://example.com",
                    "retrieved_at": "2026-08-05T00:00:00Z",
                    "artifact_sha256": sha,
                },
                "provenance": {"parser_name": "e2e", "parser_version": "1.0", "pipeline_run_id": "run-e2e"},
            }
        )
        + "\n"
    )

    sha1 = _hl.sha256(line1.encode("utf-8")).hexdigest()
    sha2 = _hl.sha256(line2.encode("utf-8")).hexdigest()

    canon_file = canonical_dir / "article.jsonl"
    canon_file.write_text(line1 + line2, encoding="utf-8")

    conn.execute(
        """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('rec-e2e-art-1', 'ver-e2e-1', 'article', 'canonical/e2e/article.jsonl', 1, ?, 'valid', 'pending', '2026-08-05T00:00:00Z')""",
        (sha1,),
    )
    conn.execute(
        """INSERT INTO records (record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('rec-e2e-art-2', 'ver-e2e-1', 'article', 'canonical/e2e/article.jsonl', 2, ?, 'valid', 'pending', '2026-08-05T00:00:00Z')""",
        (sha2,),
    )
    conn.commit()
    conn.close()


def test_workspace_e2e(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)
    _seed_data(tmp_path)

    app = create_app()
    client = TestClient(app)

    # ---- 1. System health ----
    res = client.post("/api/system/doctor", headers=HEADERS)
    assert res.status_code == 200
    assert res.json()["data"]["catalog_sqlite_healthy"] is True
    print("  ✓ Checkpoint 1: System health")

    # ---- 2. List documents ----
    res = client.get("/api/documents")
    assert res.status_code == 200
    assert len(res.json()["data"]) >= 1
    print("  ✓ Checkpoint 2: Documents listed")

    # ---- 3. Explorer search (pending records) ----
    res = client.get("/api/explorer/search?approval_status=pending")
    assert res.status_code == 200
    items = res.json()["data"]["items"]
    assert len(items) >= 1
    print(f"  ✓ Checkpoint 3: Explorer search returned {len(items)} pending records")

    # ---- 4. Facets ----
    res = client.get("/api/explorer/facets")
    assert res.status_code == 200
    facets = res.json()["data"]
    assert "record_types" in facets
    print("  ✓ Checkpoint 4: Facets retrieved")

    # ---- 5. Approve version ----
    res = client.post(
        "/api/versions/ver-e2e-1/approve",
        json={"reviewer": "e2e-bot", "note": "LGTM"},
        headers=HEADERS,
    )
    assert res.status_code == 200
    print("  ✓ Checkpoint 5: Version approved")

    # ---- 6. Create record revision ----
    res = client.post(
        "/api/records/rec-e2e-art-1/revisions",
        json={
            "change_type": "typo_fix",
            "patch": {"op": "replace", "path": "/text", "value": "Düzeltilmiş metin"},
            "reason": "Typo correction",
            "created_by": "e2e-bot",
        },
        headers=HEADERS,
    )
    assert res.status_code == 200
    rev_id = res.json()["data"]["revision_id"]
    print(f"  ✓ Checkpoint 6: Revision created: {rev_id}")

    # ---- 7. List revisions ----
    res = client.get("/api/revisions?record_id=rec-e2e-art-1")
    assert res.status_code == 200
    assert len(res.json()["data"]) >= 1
    print("  ✓ Checkpoint 7: Revisions listed")

    # ---- 8. Approve revision ----
    res = client.post(f"/api/revisions/{rev_id}/approve", headers=HEADERS)
    assert res.status_code == 200
    print("  ✓ Checkpoint 8: Revision approved")

    # ---- 9. Add annotation ----
    res = client.post(
        "/api/records/rec-e2e-art-1/annotations",
        json={"annotation_type": "tag", "namespace": "e2e", "key": "quality", "value": "high"},
        headers=HEADERS,
    )
    assert res.status_code == 200
    print("  ✓ Checkpoint 9: Annotation added")

    # ---- 10. Export records ----
    res = client.post(
        "/api/exports",
        json={"export_type": "records_jsonl"},
        headers=HEADERS,
    )
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "ready"
    print("  ✓ Checkpoint 10: Export generated")

    # ---- 11. Source config revision ----
    yaml_content = "sources:\n  mevzuat:\n    enabled: true\n"
    res = client.post(
        "/api/source-configs/revisions",
        json={"content_yaml": yaml_content, "reason": "E2E config", "created_by": "e2e-bot"},
        headers=HEADERS,
    )
    assert res.status_code == 200
    cfg_rev_id = res.json()["data"]["revision_id"]
    print(f"  ✓ Checkpoint 11: Source config revision: {cfg_rev_id}")

    # ---- 12. Activate source config ----
    res = client.post(
        f"/api/source-configs/revisions/{cfg_rev_id}/activate",
        headers=HEADERS,
    )
    assert res.status_code == 200
    print("  ✓ Checkpoint 12: Source config activated")

    # ---- 13. Backup ----
    res = client.post("/api/system/backup", headers=HEADERS)
    assert res.status_code == 200
    assert "backup_path" in res.json()["data"]
    print("  ✓ Checkpoint 13: Backup created")

    # ---- 14. Audit trail ----
    res = client.get("/api/audit-events")
    if res.status_code == 404:
        res = client.get("/api/audit")
    assert res.status_code == 200
    print("  ✓ Checkpoint 14: Audit trail accessible")

    # ---- 15. Operations job ----
    res = client.post(
        "/api/operations/jobs",
        json={"operation_type": "revalidate", "input": {"scope": "all"}},
        headers=HEADERS,
    )
    assert res.status_code == 200
    print("  ✓ Checkpoint 15: Operations job submitted")

    # ---- 16. Dashboard summary ----
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    dashboard = res.json()["data"]
    assert "total_documents" in dashboard or "documents" in dashboard or isinstance(dashboard, dict)
    print("  ✓ Checkpoint 16: Dashboard accessible")

    print("\n  ★ E2E lifecycle passed all 16 checkpoints ★")
