import pytest
import respx

from mesa_legal_data.catalog import (
    approve_version_with_checks,
    get_connection,
    get_db_path,
    migrate,
)
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.release.builder import build_release
from mesa_legal_data.release.importer import (
    ImportRollbackError,
    ReleaseNotPublished,
    get_staging_connection,
    import_release_to_staging,
)
from mesa_legal_data.sources.manual import import_manual_url
from mesa_legal_data.sources.url_fetcher import SourcePolicyError, SSRFError


@respx.mock
def test_master_security_and_scale_acceptance_gate(tmp_path, monkeypatch):
    """
    Master Acceptance Gate for Security and Scale (HARDEN-001 through HARDEN-005).
    Verifies:
    - Source policy & domain enforcement
    - Disabled source rejection
    - HTTPS enforcement
    - Pre-request private IP redirect SSRF blocking
    - Published-only release import
    - Large streaming build/import & corrupt-line rollback
    """
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    staging_db = data_root / "mesa_staging.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(staging_db))

    db_path = get_db_path()
    migrate(None, db_path)

    # 1. Wrong domain Mevzuat URL -> FAILS
    with pytest.raises(SourcePolicyError):
        import_manual_url(
            url="https://attacker.example/doc.pdf",
            source_id="mevzuat",
            document_id="tr:legislation:law:4721",
            family="legislation",
            require_https=True,
        )

    # 2. Disabled Yargitay source -> FAILS
    with pytest.raises(SourcePolicyError, match="SOURCE_DISABLED"):
        import_manual_url(
            url="https://karararama.yargitay.gov.tr/doc.html",
            source_id="yargitay",
            document_id="tr:case-law:yargitay:2026:1",
            family="decision",
            require_https=True,
        )

    # 3. Non-HTTPS (HTTP) URL -> FAILS
    with pytest.raises(SSRFError, match="HTTPS"):
        import_manual_url(
            url="http://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf",
            source_id="mevzuat",
            document_id="tr:legislation:constitution:2709",
            family="legislation",
            require_https=True,
        )

    # 4. Private IP Redirect target -> FAILS BEFORE sending request to target
    initial_url = "https://www.mevzuat.gov.tr/redirect-private"
    private_target_url = "https://127.0.0.1/secret"

    respx.get(initial_url).respond(status_code=302, headers={"Location": private_target_url})
    priv_route = respx.get(private_target_url).respond(status_code=200, text="SECRET")

    with pytest.raises(SSRFError):
        import_manual_url(
            url=initial_url,
            source_id="mevzuat",
            document_id="tr:legislation:constitution:2709",
            family="legislation",
            require_https=True,
        )
    assert not priv_route.called

    # 5. Valid HTTPS URL + Safe Same-Domain Redirect -> SUCCEEDS
    valid_url = "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf"
    valid_target = "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709_final.pdf"
    respx.get(valid_url).respond(status_code=302, headers={"Location": valid_target})
    respx.get(valid_target).respond(
        status_code=200,
        headers={"content-type": "application/pdf"},
        content="<!DOCTYPE html><html><body><h1>ANAYASA</h1><p><b>Madde 1-</b> Devlet şekli.</p></body></html>".encode(
            "utf-8"
        ),
    )

    art = import_manual_url(
        url=valid_url,
        source_id="mevzuat",
        document_id="tr:legislation:constitution:2709",
        family="legislation",
        title="Anayasa",
        require_https=True,
    )
    assert art.artifact_id.startswith("sha256:")

    # 6. Pipeline & Review
    process_artifact_pipeline(artifact_id=art.artifact_id)

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="gate_user", note="Approved")
    conn.close()

    # 7. Release Build (Status: verified)
    rel_gate = "rel-gate-1"
    build_release(release_id=rel_gate)

    # 8. Attempt Import of 'verified' (unpublished) release -> FAILS
    with pytest.raises(ReleaseNotPublished):
        import_release_to_staging(rel_gate)

    # 9. Publish Release
    conn = get_connection()
    conn.execute("UPDATE releases SET status = 'published' WHERE release_id = ?", (rel_gate,))
    conn.close()

    # 10. Import Published Release -> SUCCEEDS
    res_imp = import_release_to_staging(rel_gate)
    assert res_imp["status"] == "imported"

    # 11. Idempotent second import -> ALREADY IMPORTED NO-OP
    res_imp_again = import_release_to_staging(rel_gate)
    assert res_imp_again["status"] == "already_imported"

    # 12. Active release pointer verified in Staging DB
    stg_conn = get_staging_connection()
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel_gate
    stg_conn.close()

    # 13. Large Streaming & Corrupt Line Rollback Test
    rel_corrupt = "rel-gate-corrupt"
    build_release(release_id=rel_corrupt)
    conn = get_connection()
    conn.execute("UPDATE releases SET status = 'published' WHERE release_id = ?", (rel_corrupt,))
    conn.close()

    # Inject corrupt non-JSON line into articles file
    articles_file = data_root / "releases" / rel_corrupt / "data" / "articles.jsonl"
    articles_file.write_text("CORRUPTED_NON_JSON_LINE\n", encoding="utf-8")

    with pytest.raises((ImportRollbackError, Exception)):
        import_release_to_staging(rel_corrupt)

    # 14. Verify active release pointer remained rel_gate and no partial corrupt records inserted
    stg_conn = get_staging_connection()
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel_gate

    stg_cur.execute("SELECT count(*) FROM staging_records WHERE release_id = ?", (rel_corrupt,))
    assert stg_cur.fetchone()[0] == 0
    stg_conn.close()
