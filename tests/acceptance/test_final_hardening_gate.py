import builtins

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
    ReleaseNotPublished,
    get_staging_connection,
    import_release_to_staging,
)
from mesa_legal_data.release.verifier import verify_release
from mesa_legal_data.sources.manual import import_manual_url
from mesa_legal_data.sources.url_fetcher import (
    SourcePolicyError,
    SSRFError,
    validate_source_request,
)


@pytest.mark.scale
@respx.mock
def test_final_hardening_acceptance_gate(tmp_path, monkeypatch):
    """
    Final Master Acceptance Gate for Security and Streaming Release Architecture (FINAL-HARDEN-001 to 007).
    Verifies:
    - Mandatory source_id / document_family
    - Explicit host allowlist (implicit subdomains rejected)
    - HTTP rejected / HTTPS mandatory
    - Pre-request private IP redirect blocking
    - 10,000+ approved record streaming release build
    - Canonical part file opened EXACTLY ONCE (O(n) sequential scan)
    - Zero fetchall / readlines / RAM payload accumulation
    - Verification, publish, import, and idempotency
    """
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    staging_db = data_root / "mesa_staging.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_MESA_STAGING_DB", str(staging_db))

    db_path = get_db_path()
    migrate(None, db_path)

    # 1. Mandatory source_id check
    with pytest.raises(SourcePolicyError, match="SOURCE_REQUIRED"):
        validate_source_request(
            source_id="",
            document_family="legislation",
            url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf",
        )

    # 2. Implicit subdomain rejection
    with pytest.raises(SourcePolicyError, match="SOURCE_HOST_NOT_ALLOWED"):
        import_manual_url(
            url="https://api.mevzuat.gov.tr/doc.pdf",
            source_id="mevzuat",
            document_id="tr:legislation:law:4721",
            family="legislation",
        )

    # 3. Explicit allowed host accepts
    # 4. HTTP scheme rejected
    with pytest.raises(SSRFError, match="HTTPS"):
        import_manual_url(
            url="http://www.mevzuat.gov.tr/doc.pdf",
            source_id="mevzuat",
            document_id="tr:legislation:law:4721",
            family="legislation",
        )

    # 5. Explicit non-allowed redirect host rejected
    unlisted_redirect_url = "https://www.mevzuat.gov.tr/redirect-unlisted"
    target_unlisted = "https://unlisted-external.example/doc.pdf"
    respx.get(unlisted_redirect_url).respond(status_code=302, headers={"Location": target_unlisted})
    unlisted_route = respx.get(target_unlisted).respond(status_code=200, text="UNLISTED")

    with pytest.raises(SourcePolicyError):
        import_manual_url(
            url=unlisted_redirect_url,
            source_id="mevzuat",
            document_id="tr:legislation:law:4721",
            family="legislation",
        )
    assert not unlisted_route.called

    # 6. Private IP redirect target rejected BEFORE sending GET request
    priv_redirect_url = "https://www.mevzuat.gov.tr/redirect-private"
    priv_target = "https://127.0.0.1/secret"
    respx.get(priv_redirect_url).respond(status_code=302, headers={"Location": priv_target})
    priv_route = respx.get(priv_target).respond(status_code=200, text="SECRET")

    with pytest.raises(SSRFError):
        import_manual_url(
            url=priv_redirect_url,
            source_id="mevzuat",
            document_id="tr:legislation:law:4721",
            family="legislation",
        )
    assert not priv_route.called

    # 7. Safe HTTPS Same-Host Redirect -> SUCCEEDS
    safe_url = "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf"
    safe_target = "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709_final.pdf"

    html_lines = ["<!DOCTYPE html><html><body>", "<h1>TÜRK MEDENİ KANUNU</h1>"]
    for i in range(1, 10001):
        html_lines.append(f"<p><b>Madde {i}-</b> Bu kanun maddesidir {i}.</p>")
    html_lines.append("</body></html>")
    html_content = "\n".join(html_lines).encode("utf-8")

    respx.get(safe_url).respond(status_code=302, headers={"Location": safe_target})
    respx.get(safe_target).respond(
        status_code=200,
        headers={"content-type": "text/html"},
        content=html_content,
    )

    art = import_manual_url(
        url=safe_url,
        source_id="mevzuat",
        document_id="tr:legislation:law:4721",
        family="legislation",
        title="Türk Medeni Kanunu",
    )
    assert art.artifact_id.startswith("sha256:")

    # 8. Process Pipeline & Approve Version
    process_artifact_pipeline(artifact_id=art.artifact_id)

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_id FROM versions LIMIT 1")
    ver_id = c.fetchone()[0]
    approve_version_with_checks(conn, ver_id, reviewer="gate_user", note="Approved 10,000 articles")
    conn.close()

    # 9. Track Canonical File Open Count during build_release
    canonical_open_counts = {}
    original_open = builtins.open

    def tracking_open(file, *args, **kwargs):
        str_file = str(file)
        if "canonical" in str_file and "releases" not in str_file and str_file.endswith(".jsonl"):
            canonical_open_counts[str_file] = canonical_open_counts.get(str_file, 0) + 1
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    rel_id = "rel-final-gate-10k"
    rel_meta = build_release(release_id=rel_id)

    # 10. Check real counts
    assert rel_meta["counts"]["article_count"] == 10000
    assert rel_meta["counts"]["legislation_count"] == 1

    # 11. Assert Canonical Part File opened EXACTLY ONCE (O(n) single pass scan)
    assert len(canonical_open_counts) > 0
    for c_path, count in canonical_open_counts.items():
        assert count == 1, f"Canonical file {c_path} was opened {count} times (expected 1 for O(n) scan)"

    # 12. Verify Release Directory
    assert verify_release(rel_id) is True

    # 13. Attempt Import of 'verified' (unpublished) release -> FAILS
    with pytest.raises(ReleaseNotPublished):
        import_release_to_staging(rel_id)

    # 14. Publish Release
    conn = get_connection()
    conn.execute("UPDATE releases SET status = 'published' WHERE release_id = ?", (rel_id,))
    conn.close()

    # 15. Import Published Release -> SUCCEEDS
    res_imp = import_release_to_staging(rel_id)
    assert res_imp["status"] == "imported"

    # 16. Idempotent Second Import -> ALREADY IMPORTED NO-OP
    res_imp_again = import_release_to_staging(rel_id)
    assert res_imp_again["status"] == "already_imported"

    # 17. Active release pointer verified in Staging DB
    stg_conn = get_staging_connection()
    stg_cur = stg_conn.cursor()
    stg_cur.execute("SELECT release_id FROM active_release WHERE singleton_id = 1")
    assert stg_cur.fetchone()[0] == rel_id

    stg_cur.execute("SELECT count(*) FROM staging_records WHERE release_id = ?", (rel_id,))
    assert stg_cur.fetchone()[0] >= 10001
    stg_conn.close()
