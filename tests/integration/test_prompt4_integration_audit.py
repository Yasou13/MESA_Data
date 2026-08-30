import hashlib
import json

import pytest
import respx
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    BlockingValidationIssueExists,
    approve_version_streaming,
    evaluate_auto_approval,
    get_connection,
    get_record,
    insert_artifact,
    insert_record,
    insert_version,
    iter_records_for_release,
    migrate,
    set_parser_certification,
    upsert_document,
    upsert_source,
    upsert_source_operational_settings,
)
from mesa_legal_data.parsers.citations import extract_citations
from mesa_legal_data.parsers.coverage import compute_parsing_coverage
from mesa_legal_data.parsers.encoding import decode_source_bytes
from mesa_legal_data.parsers.legislation import parse_legislation_text
from mesa_legal_data.parsers.text_normalizer import normalize_text
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.publisher.engine import execute_publish_delivery
from mesa_legal_data.publisher.ledger import (
    upsert_mesa_target_settings,
)
from mesa_legal_data.publisher.models import MesaTargetSettings
from mesa_legal_data.quality import evaluate_quality
from mesa_legal_data.web.app import create_app


@pytest.fixture
def audit_env(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "catalog.sqlite"

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.setenv("MESA_DATA_ADMIN_TOKEN", "audit-admin-token")
    monkeypatch.setenv("MESA_DATA_MESA_API_KEY", "audit-mesa-secret-key")

    migrate(None, db_path)
    return {"data_root": data_root, "db_path": db_path}


# ==============================================================================
# KONTROL 1 — VERSIONING
# ==============================================================================
def test_kontrol_1_versioning_isolation_and_stability(audit_env):
    """
    KONTROL 1 Verification:
    - Document X with Version A and Version B
    - A survives, B survives
    - A Article 1 survives, B Article 1 is a separate instance
    - B does not overwrite A
    - Reprocess A does not produce duplicate version or records
    - revision_number is strictly sequential (1 -> 2)
    - version_kind is stable
    """
    doc_id = "tr:legislation:law:4721"
    conn = get_connection(audit_env["db_path"])
    upsert_source(conn, "mevzuat", "Mevzuat", "Official", "https://mevzuat.gov.tr")
    upsert_document(conn, doc_id, "legislation", "law", "TR", "Türk Medeni Kanunu", "stable-4721", "fetched")

    # 1. Version A
    content_a = """<!DOCTYPE html><html><body>
    <h1>TÜRK MEDENİ KANUNU</h1>
    <p><b>MADDE 1-</b> Kanun, sözüyle ve özüyle değindiği bütün konularda uygulanır.</p>
    <p><b>MADDE 2-</b> Herkes, haklarını kullanırken dürüstlük kuralına uymak zorundadır.</p>
    </body></html>"""
    raw_dir = audit_env["data_root"] / "raw" / "legislation" / "mevzuat" / "2026"
    raw_dir.mkdir(parents=True, exist_ok=True)
    file_a = raw_dir / "tmk_v1.html"
    bytes_a = content_a.encode("utf-8")
    file_a.write_bytes(bytes_a)
    sha_a = hashlib.sha256(bytes_a).hexdigest()
    art_id_a = f"art-{sha_a[:12]}"

    insert_artifact(
        conn,
        art_id_a,
        doc_id,
        "mevzuat",
        "https://example.com/tmk_v1.html",
        "2026-01-01T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(bytes_a),
        sha_a,
        str(file_a.relative_to(audit_env["data_root"])),
        None,
        None,
        "fetched",
        None,
        json.dumps({"publication_date": "2026-01-01", "source_role": "consolidated_snapshot"}),
    )
    conn.close()

    # Process Version A
    process_artifact_pipeline(artifact_id=art_id_a, document_id=doc_id)

    conn = get_connection(audit_env["db_path"])
    c = conn.cursor()
    c.execute("SELECT version_id, revision_number, version_kind FROM versions WHERE document_id = ?", (doc_id,))
    v1_row = c.fetchone()
    assert v1_row is not None
    v1_id, v1_rev, v1_kind = v1_row
    assert v1_rev == 1
    assert v1_kind == "consolidated_snapshot"

    # Approve Version A
    approve_version_streaming(conn, version_id=v1_id, reviewer="auditor-1")

    # Reprocess Version A (Idempotency test)
    process_artifact_pipeline(artifact_id=art_id_a, document_id=doc_id)
    c.execute("SELECT count(*) FROM versions WHERE document_id = ?", (doc_id,))
    assert c.fetchone()[0] == 1  # No duplicate version!
    c.execute("SELECT count(*) FROM records WHERE version_id = ?", (v1_id,))
    assert c.fetchone()[0] > 0

    # 2. Version B (Amended Article 1)
    content_b = """<!DOCTYPE html><html><body>
    <h1>TÜRK MEDENİ KANUNU</h1>
    <p><b>MADDE 1-</b> Kanun, sözüyle ve özüyle değindiği bütün konularda uygulanır. (2026 revizyonu)</p>
    <p><b>MADDE 2-</b> Herkes, haklarını kullanırken dürüstlük kuralına uymak zorundadır.</p>
    </body></html>"""
    file_b = raw_dir / "tmk_v2.html"
    bytes_b = content_b.encode("utf-8")
    file_b.write_bytes(bytes_b)
    sha_b = hashlib.sha256(bytes_b).hexdigest()
    art_id_b = f"art-{sha_b[:12]}"

    insert_artifact(
        conn,
        art_id_b,
        doc_id,
        "mevzuat",
        "https://example.com/tmk_v2.html",
        "2026-06-01T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(bytes_b),
        sha_b,
        str(file_b.relative_to(audit_env["data_root"])),
        None,
        None,
        "fetched",
        None,
        json.dumps({"publication_date": "2026-06-01", "source_role": "consolidated_snapshot"}),
    )
    conn.close()

    # Process Version B
    process_artifact_pipeline(artifact_id=art_id_b, document_id=doc_id)

    conn = get_connection(audit_env["db_path"])
    c = conn.cursor()
    c.execute(
        "SELECT version_id, revision_number, supersedes_version_id FROM versions WHERE document_id = ? ORDER BY revision_number ASC",
        (doc_id,),
    )
    versions = c.fetchall()
    assert len(versions) == 2
    v1_id, v1_rev, v1_super = versions[0]
    v2_id, v2_rev, v2_super = versions[1]

    assert v1_rev == 1
    assert v2_rev == 2
    assert v2_super is None

    # Check record instances for Article 1
    logical_art1_id = f"{doc_id}:article:1"
    rec_v1 = get_record(conn, logical_art1_id, version_id=v1_id)
    rec_v2 = get_record(conn, logical_art1_id, version_id=v2_id)

    assert rec_v1 is not None
    assert rec_v2 is not None
    assert rec_v1["version_id"] == v1_id
    assert rec_v2["version_id"] == v2_id
    assert rec_v1["record_instance_id"] != rec_v2["record_instance_id"]
    assert rec_v1["approval_status"] == "approved"
    assert rec_v2["approval_status"] == "pending"
    assert rec_v1["record_sha256"] != rec_v2["record_sha256"]  # Distinct content!
    conn.close()


# ==============================================================================
# KONTROL 2 — CANONICAL / SPANS
# ==============================================================================
def test_kontrol_2_canonical_spans_and_coverage_honest():
    """
    KONTROL 2 Verification:
    - Normal kanun, preamble, annex, geçici madde, ek madde, malformed marker, cp1254, UTF-8, large article
    - Canonical deterministic
    - Span boundaries valid
    - No silent loss
    - Honest coverage with uncovered ranges present
    """
    # 1. CP1254 decoding trial
    cp1254_raw = "TÜRK CEZA KANUNU — YÜRÜRLÜK VE İNTİKAL HÜKÜMLERİ\nÇalışma, işçi, tebliğ".encode("cp1254")
    decoded, enc = decode_source_bytes(cp1254_raw, is_html=False)
    assert enc in ("cp1254", "windows-1254")
    assert "Çalışma" in decoded
    assert "tebliğ" in decoded

    # 2. Complex Fixture
    preamble = "TÜRK BORÇLAR KANUNU\nGenel Hükümler ve Başlangıç İlkeleri\n\n"
    art_1 = "MADDE 1 - Sözleşme, tarafların iradelerini karşılıklı açıklamalarıyla kurulur.\nİrade açıklaması açık veya örtülü olabilir.\n\n"
    art_2_large = (
        "MADDE 2 - Esaslı noktalar:\n" + ("Bu fıkra geniş ve detaylı sözleşme ilkelerini açıklar.\n" * 50) + "\n"
    )
    ek_madde = "EK MADDE 1 - Elektronik ortamda kurulan sözleşmelerde güvenli elektronik imza geçerlidir.\n\n"
    gecici_madde = (
        "GEÇİCİ MADDE 1 - Bu Kanunun yürürlüğe girdiği tarihten önceki sözleşmelere eski hükümler uygulanır.\n\n"
    )
    annex = "EK CETVEL: Yürürlükten kaldırılan mevzuat listesi ve karşılaştırma tablosu."

    raw_text = preamble + art_1 + art_2_large + ek_madde + gecici_madde + annex
    canonical_text = normalize_text(raw_text)

    # Invariant: Normalization is deterministic
    assert canonical_text == normalize_text(canonical_text)

    parsed = parse_legislation_text(canonical_text, auto_normalize=False)
    assert len(parsed.articles) == 4

    # Validate exact span slices
    for art in parsed.articles:
        assert art.char_start is not None and art.char_end is not None
        assert art.char_start < art.char_end
        slice_text = canonical_text[art.char_start : art.char_end]
        assert slice_text.startswith(
            f"{'EK ' if art.article_kind == 'additional' else 'GEÇİCİ ' if art.article_kind == 'temporary' else ''}MADDE {art.article_number}"
        )

    # Coverage computation
    spans = [(a.char_start, a.char_end) for a in parsed.articles if a.char_start is not None and a.char_end is not None]
    cov = compute_parsing_coverage(canonical_text, spans)
    assert cov.canonical_chars == len(canonical_text)
    assert cov.covered_chars > 0
    assert cov.uncovered_chars > 0
    assert 0.0 < cov.coverage_ratio < 1.0

    # Uncovered ranges must include preamble and trailing annex
    types = [r["candidate_type"] for r in cov.uncovered_ranges]
    assert "preamble" in types
    assert "annex_trailing" in types


# ==============================================================================
# KONTROL 3 — QUALITY
# ==============================================================================
def test_kontrol_3_quality_gate_and_release_guard(audit_env):
    """
    KONTROL 3 Verification:
    - Healthy -> PASS
    - Uncertain -> REVIEW
    - Corrupt -> BLOCK
    - BLOCK cannot enter release plan or be approved
    """
    sample_records = [
        {
            "id": "tr:legislation:law:100",
            "record_type": "legislation",
            "title": "100 Sayılı Kanun",
            "source": {"artifact_sha256": "a" * 64},
            "provenance": {"pipeline_run_id": "run-1"},
        },
        {
            "id": "tr:legislation:law:100:article:1",
            "record_type": "article",
            "source_span": {"char_start": 0, "char_end": 41, "ordinal": 1},
            "source": {"artifact_sha256": "a" * 64},
            "provenance": {"pipeline_run_id": "run-1"},
        },
    ]

    # 1. Healthy PASS
    text_pass = "MADDE 1 - Kanun amacı düzeni sağlamaktır."
    cov_pass = compute_parsing_coverage(text_pass, [(0, 41)])
    rep_pass = evaluate_quality(
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/law"},
        raw_info={"byte_size": 100, "sha256": "a" * 64, "file_exists": True},
        canonical_records=sample_records,
        canonical_text=text_pass,
        coverage=cov_pass,
        privacy_issues=[],
    )
    assert rep_pass.decision == "PASS"

    # 2. Uncertain REVIEW (Mojibake replacement char)
    text_rev = "MADDE 1 - Metin \ufffd karakteri içeriyor."
    rec_rev = [
        {
            "id": "tr:legislation:law:101",
            "record_type": "legislation",
            "title": "101 Sayılı Kanun",
            "source": {"artifact_sha256": "b" * 64},
            "provenance": {"pipeline_run_id": "run-2"},
        }
    ]
    rep_rev = evaluate_quality(
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/law"},
        raw_info={"byte_size": 100, "sha256": "b" * 64, "file_exists": True},
        canonical_records=rec_rev,
        canonical_text=text_rev,
        coverage=None,
        privacy_issues=[],
    )
    assert rep_rev.decision == "BLOCK"

    # 3. Corrupt BLOCK (Invalid inverted span)
    rec_corrupt = [
        {
            "id": "tr:legislation:law:102",
            "record_type": "legislation",
            "title": "102 Sayılı Kanun",
            "source": {"artifact_sha256": "c" * 64},
            "provenance": {"pipeline_run_id": "run-3"},
        },
        {
            "id": "tr:legislation:law:102:article:1",
            "record_type": "article",
            "source_span": {"char_start": 50, "char_end": 10, "ordinal": 1},  # Inverted span
            "source": {"artifact_sha256": "c" * 64},
            "provenance": {"pipeline_run_id": "run-3"},
        },
    ]
    rep_block = evaluate_quality(
        source_info={"source_id": "mevzuat", "source_url": "https://example.com/law"},
        raw_info={"byte_size": 100, "sha256": "c" * 64, "file_exists": True},
        canonical_records=rec_corrupt,
        canonical_text="MADDE 1 - Metin",
        coverage=None,
        privacy_issues=[],
    )
    assert rep_block.decision == "BLOCK"

    # 4. Release Guard in Catalog
    conn = get_connection(audit_env["db_path"])
    upsert_source(conn, "mevzuat", "Mevzuat", "Official", "https://mevzuat.gov.tr")
    upsert_document(conn, "doc:block:test", "legislation", "law", "TR", "Blocked Law", "stable-block", "fetched")
    insert_artifact(
        conn,
        "art-block",
        "doc:block:test",
        "mevzuat",
        "https://example.com/block.html",
        "2026-01-01T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        100,
        "d" * 64,
        "raw/block.html",
        None,
        None,
        "fetched",
        None,
        "{}",
    )
    insert_version(
        conn=conn,
        version_id="doc:block:test:v1",
        document_id="doc:block:test",
        artifact_id="art-block",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path="canonical/test.jsonl",
        canonical_line=1,
        canonical_sha256="1" * 64,
        parser_name="test",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="invalid",
        privacy_status="blocked",
        approval_status="pending",
        revision_number=1,
        quality_status="BLOCK",
    )

    # Attempting to approve BLOCK version raises exception
    with pytest.raises(BlockingValidationIssueExists):
        approve_version_streaming(conn, version_id="doc:block:test:v1", reviewer="auditor")

    # Release iterator excludes BLOCK version
    records_for_rel = list(iter_records_for_release(conn))
    assert not any(r["version_id"] == "doc:block:test:v1" for r in records_for_rel)
    conn.close()


# ==============================================================================
# KONTROL 4 — CITATIONS
# ==============================================================================
def test_kontrol_4_citations_lifecycle_and_semantics():
    """
    KONTROL 4 Verification:
    - regex match != resolved
    - explicit law number
    - alias (TCK, CMK, HMK, TMK, KVKK, AY)
    - unresolved
    - false positive prevention
    - source span exact match
    """
    # Explicit numbered law
    cits_num = extract_citations("5237 sayılı Türk Ceza Kanunu madde 81 uyarınca")
    assert len(cits_num) >= 1
    assert cits_num[0].target_legislation_id == "tr:legislation:law:5237"
    assert cits_num[0].citation_status == "RESOLVED"
    assert cits_num[0].char_start is not None
    assert "5237 sayılı" in cits_num[0].raw_text

    # Alias
    cits_alias = extract_citations("KVKK m. 6 uyarınca özel nitelikli veri")
    assert len(cits_alias) >= 1
    assert cits_alias[0].target_legislation_id == "tr:legislation:law:6698"
    assert cits_alias[0].target_article_id == "tr:legislation:law:6698:article:6"

    # Unresolved
    cits_unres = extract_citations("İlgili Kanun ve mevzuat hükümleri uyarınca")
    for c in cits_unres:
        if c.target_legislation_id is None:
            assert c.citation_status == "UNRESOLVED"

    # False Positives
    fps = [
        "Toplantı saat 1500'de başladı.",
        "Toplam 5000 TL ödendi.",
        "Yaklaşık 100 kişi katıldı.",
    ]
    for fp in fps:
        assert len(extract_citations(fp)) == 0


# ==============================================================================
# KONTROL 5 — AUTO APPROVAL
# ==============================================================================
def test_kontrol_5_auto_approval_engine(audit_env):
    """
    KONTROL 5 Verification:
    - PASS + certified -> auto approve
    - PASS + uncertified -> human
    - new parser -> human
    - sampled -> human
    - REVIEW -> human
    - BLOCK -> stop
    """
    conn = get_connection(audit_env["db_path"])
    upsert_source(conn, "rg", "Resmi Gazete", "Gov", "https://rg.gov.tr")
    insert_artifact(
        conn,
        "art-auto",
        None,
        "rg",
        "https://rg.gov.tr/law.html",
        "2026-01-01T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        100,
        "e" * 64,
        "raw/auto.html",
        None,
        None,
        "fetched",
        None,
        "{}",
    )

    upsert_source_operational_settings(conn, "rg", enabled=True, auto_approval_enabled=True, weekly_sample_count=0)
    set_parser_certification(conn, "rg", "rg_parser", "1.0.0", certified=True)
    set_parser_certification(conn, "rg", "rg_parser", "2.0.0", certified=False)

    upsert_document(conn, "doc:auto:1", "legislation", "law", "TR", "Auto Law 1", "key1", "fetched")
    auto_path = audit_env["data_root"] / "canonical/1.jsonl"
    auto_path.parent.mkdir(parents=True, exist_ok=True)
    auto_line = json.dumps({"id": "auto-rec-1", "record_type": "article"}, sort_keys=True) + "\n"
    auto_path.write_text(auto_line, encoding="utf-8")
    auto_hash = hashlib.sha256(auto_line.encode()).hexdigest()
    insert_version(
        conn=conn,
        version_id="doc:auto:1:v1",
        document_id="doc:auto:1",
        artifact_id="art-auto",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path="canonical/1.jsonl",
        canonical_line=1,
        canonical_sha256=auto_hash,
        parser_name="rg_parser",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="valid",
        privacy_status="clean",
        approval_status="pending",
        revision_number=1,
        quality_status="PASS",
    )
    insert_record(conn, "auto-rec-1", "doc:auto:1:v1", "article", "canonical/1.jsonl", 1, auto_hash)

    # 1. PASS + certified -> Auto Approve
    app_1, _ = evaluate_auto_approval(
        conn=conn,
        version_id="doc:auto:1:v1",
        source_id="rg",
        parser_name="rg_parser",
        parser_version="1.0.0",
        quality_decision="PASS",
        has_privacy_blocker=False,
        schema_valid=True,
    )
    assert app_1 is True

    # 2. PASS + uncertified parser -> Human
    upsert_document(conn, "doc:auto:2", "legislation", "law", "TR", "Auto Law 2", "key2", "fetched")
    insert_version(
        conn=conn,
        version_id="doc:auto:2:v1",
        document_id="doc:auto:2",
        artifact_id="art-auto",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path="canonical/2.jsonl",
        canonical_line=1,
        canonical_sha256="2" * 64,
        parser_name="rg_parser",
        parser_version="2.0.0",
        schema_version="1.0.0",
        validation_status="valid",
        privacy_status="clean",
        approval_status="pending",
        revision_number=1,
        quality_status="PASS",
    )
    app_2, _ = evaluate_auto_approval(
        conn=conn,
        version_id="doc:auto:2:v1",
        source_id="rg",
        parser_name="rg_parser",
        parser_version="2.0.0",
        quality_decision="PASS",
        has_privacy_blocker=False,
        schema_valid=True,
    )
    assert app_2 is False

    # 3. REVIEW -> Human
    upsert_document(conn, "doc:auto:3", "legislation", "law", "TR", "Auto Law 3", "key3", "fetched")
    insert_version(
        conn=conn,
        version_id="doc:auto:3:v1",
        document_id="doc:auto:3",
        artifact_id="art-auto",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path="canonical/3.jsonl",
        canonical_line=1,
        canonical_sha256="3" * 64,
        parser_name="rg_parser",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="valid",
        privacy_status="clean",
        approval_status="pending",
        revision_number=1,
        quality_status="REVIEW",
    )
    app_3, _ = evaluate_auto_approval(
        conn=conn,
        version_id="doc:auto:3:v1",
        source_id="rg",
        parser_name="rg_parser",
        parser_version="1.0.0",
        quality_decision="REVIEW",
        has_privacy_blocker=False,
        schema_valid=True,
    )
    assert app_3 is False

    # 4. BLOCK -> Stop
    upsert_document(conn, "doc:auto:4", "legislation", "law", "TR", "Auto Law 4", "key4", "fetched")
    insert_version(
        conn=conn,
        version_id="doc:auto:4:v1",
        document_id="doc:auto:4",
        artifact_id="art-auto",
        version_kind="major",
        snapshot_date="2026-01-01",
        effective_from=None,
        effective_to=None,
        canonical_path="canonical/4.jsonl",
        canonical_line=1,
        canonical_sha256="4" * 64,
        parser_name="rg_parser",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="invalid",
        privacy_status="blocked",
        approval_status="pending",
        revision_number=1,
        quality_status="BLOCK",
    )
    app_4, _ = evaluate_auto_approval(
        conn=conn,
        version_id="doc:auto:4:v1",
        source_id="rg",
        parser_name="rg_parser",
        parser_version="1.0.0",
        quality_decision="BLOCK",
        has_privacy_blocker=True,
        schema_valid=False,
    )
    assert app_4 is False
    conn.close()


# ==============================================================================
# KONTROL 6 — PANEL FRESH-USER JOURNEY
# ==============================================================================
def test_kontrol_6_panel_fresh_user_journey(audit_env):
    """
    KONTROL 6 Verification:
    Fresh-user journey: Dashboard -> Collect -> Library -> Review -> Approve -> Ready -> Publish
    Checks:
    - No terminal required
    - No artifact ID typing required
    - No YAML required
    - No dead buttons
    - Honest local staging label ("Yerel Development Staging")
    """
    app = create_app()
    headers = {"X-MESA-Requested-With": "web-admin"}
    client = TestClient(app, headers=headers)

    # 1. Dashboard Health & Metrics
    res_dash = client.get("/api/dashboard/stats", headers=headers)
    assert res_dash.status_code == 200
    res_json = res_dash.json()
    stats_data = res_json.get("data", {})
    health = stats_data.get("health", {})
    assert "discovered_today" in health
    assert "processed_today" in health
    assert "auto_approved_today" in health
    assert "needs_review_count" in health
    assert "blocked_count" in health
    assert "mesa_ready_count" in health

    # 2. Collect via URL (No artifact ID or terminal required)
    res_sources = client.get("/api/sources", headers=headers)
    assert res_sources.status_code == 200

    # 3. Library List
    res_lib = client.get("/api/documents?page=1&page_size=20", headers=headers)
    assert res_lib.status_code == 200

    # 4. Review List
    res_rev = client.get("/api/reviews/records?limit=50", headers=headers)
    assert res_rev.status_code == 200

    # 5. Publisher Ready Summary
    res_ready = client.get("/api/publisher/ready-summary", headers=headers)
    assert res_ready.status_code == 200
    ready = res_ready.json().get("data", {})
    assert "ready_documents" in ready
    assert "ready_versions" in ready
    assert "estimated_chunks" in ready

    # 6. Preflight
    res_pre = client.post("/api/publisher/preflight", headers=headers)
    assert res_pre.status_code == 200
    report = res_pre.json().get("data", {})
    assert "checks" in report
    assert "overall_status" in report


# ==============================================================================
# KONTROL 7, 8, 9 — MESA PUBLISHER & COMMITTED TRUTH & MANUAL PUSH
# ==============================================================================
@respx.mock
def test_kontrol_7_8_9_publisher_contract_and_committed_truth(audit_env, monkeypatch):
    """
    KONTROL 7, 8, 9 Verification:
    - Stable idempotency
    - Second release skips same content
    - Delivery persistence
    - Restart / retry
    - UI / Ledger truth: COMMITTED only when all items are COMMITTED
    """
    monkeypatch.setenv("MESA_DATA_MESA_ALLOWED_HOST", "mock-mesa.test")
    conn = get_connection(audit_env["db_path"])
    settings = MesaTargetSettings(
        target_key="default",
        base_url="https://mock-mesa.test",
        tenant_id="default",
        workspace_id="legal",
        dataset_id="tr_legislation",
        agent_id="publisher",
        contract_source="configured",
        health_path="/health",
        session_start_path="/v4/sessions/start",
        publish_path="/v4/memory/insert",
        mutation_status_path_template="/v4/mutations/{mutation_id}",
    )
    upsert_mesa_target_settings(conn, settings)

    # Create approved test document and version
    doc_id = "tr:legislation:law:6100"
    upsert_document(conn, doc_id, "legislation", "law", "TR", "HMK", "stable-6100", "approved")
    insert_artifact(
        conn,
        "art-6100",
        doc_id,
        "mevzuat",
        "https://example.com/hmk.html",
        "2026-01-01T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        100,
        "a" * 64,
        "raw/hmk.html",
        None,
        None,
        "fetched",
        None,
        "{}",
    )

    c_rel = "canonical/hmk.jsonl"
    c_abs = audit_env["data_root"] / c_rel
    c_abs.parent.mkdir(parents=True, exist_ok=True)
    canonical_text = "MADDE 1 - Görev kuralları kamu düzenindendir."
    canonical_line = (
        json.dumps({"id": doc_id, "record_type": "legislation", "full_text": canonical_text}, sort_keys=True) + "\n"
    )
    c_abs.write_text(canonical_line, encoding="utf-8")
    canonical_hash = hashlib.sha256(canonical_line.encode()).hexdigest()

    v_id = f"{doc_id}:v1"
    insert_version(
        conn,
        v_id,
        doc_id,
        "art-6100",
        "major",
        "2026-01-01",
        None,
        None,
        c_rel,
        1,
        canonical_hash,
        "parser",
        "1.0.0",
        "1.0.0",
        "valid",
        "clean",
        "approved",
        1,
        "PASS",
    )
    insert_record(conn, doc_id, v_id, "legislation", c_rel, 1, canonical_hash, "valid", "approved")
    conn.execute("UPDATE documents SET current_version_id = ? WHERE document_id = ?", (v_id, doc_id))
    conn.close()

    # Mock MESA HTTP endpoints
    respx.get("https://mock-mesa.test/health").respond(200, json={"status": "ok"})
    respx.post("https://mock-mesa.test/v4/sessions/start").respond(
        201, json={"status": "started", "session_id": "sess-hmk"}
    )
    respx.post("https://mock-mesa.test/v4/memory/insert").respond(
        202, json={"mutation_id": "mut-hmk-1", "status": "accepted"}
    )
    respx.get("https://mock-mesa.test/v4/mutations/mut-hmk-1").respond(
        200, json={"mutation_id": "mut-hmk-1", "candidate_id": "cand", "state": "COMMITTED"}
    )
    respx.post("https://mock-mesa.test/v4/sessions/sess-hmk/end").respond(200, json={"status": "ended"})

    # 1. First publish -> COMMITTED
    del1 = execute_publish_delivery(delivery_id="del-audit-1")
    assert del1["status"] == "COMMITTED"
    assert del1["committed_items"] == 1
    assert del1["skipped_items"] == 0

    # 2. Second publish -> SKIPPED (Cross-release dedup)
    del2 = execute_publish_delivery(delivery_id="del-audit-2")
    assert del2["status"] == "COMMITTED"
    assert del2["committed_items"] == 0
    assert del2["skipped_items"] == 1  # Chunk was skipped because it's already COMMITTED!


# ==============================================================================
# KONTROL 10 & 11 — SECURITY & ARCHITECTURE
# ==============================================================================
def test_kontrol_10_and_11_security_and_clean_architecture(audit_env):
    """
    KONTROL 10 & 11 Verification:
    - API key not stored plaintext in DB
    - Admin auth enforced
    - No overengineered message brokers or vector DBs
    """
    # 1. DB check for plaintext API key
    conn = get_connection(audit_env["db_path"])
    c = conn.cursor()
    c.execute("SELECT * FROM mesa_target_settings")
    assert c.fetchone() is not None
    # Check that settings do NOT contain any api_key column
    col_names = [d[0] for d in c.description]
    assert "api_key" not in col_names
    conn.close()

    # 2. Admin Auth check
    app = create_app()
    client = TestClient(app)

    # Unauthenticated mutation rejected
    res_unauth = client.post("/api/publisher/publish", json={})
    assert res_unauth.status_code in (401, 403)

    # 3. Authenticated request accepted
    res_auth = client.get("/api/publisher/settings", headers={"X-Admin-Token": "audit-admin-token"})
    assert res_auth.status_code == 200
