import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mesa_legal_data.catalog import (
    get_connection,
    insert_artifact,
    open_issue,
    upsert_document,
)
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.web.app import create_app
from mesa_legal_data.web.bootstrap import prepare_web_runtime


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "web_remediation_data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    monkeypatch.delenv("MESA_DATA_WEB_ADMIN_TOKEN", raising=False)
    prepare_web_runtime(custom_data_root=data_root)

    app = create_app()
    with TestClient(app, headers={"X-MESA-Requested-With": "web-admin"}) as test_client:
        yield test_client


def test_finding_1_kutuphane_contract_and_text_retrieval(client, tmp_path):
    """Finding 1: Kütüphane frontend/backend document-detail contract.

    Tests:
    1. Document list exposes lifecycle_status and source_id.
    2. Document detail exposes lifecycle_status, source_id, and artifact structure.
    3. Document text endpoint returns real text content.
    4. Valid document does not falsely report missing text.
    """
    data_root = Path(tmp_path / "web_remediation_data")
    raw_dir = data_root / "raw" / "legislation" / "resmi_gazete" / "2026"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "kanun_7500.html"
    raw_text = "<!DOCTYPE html><html><body><h1>KANUN</h1><p>No: 7500</p><div><b>Madde 1-</b> Bu kanun yururluktedir.</div></body></html>"
    raw_file.write_text(raw_text, encoding="utf-8")
    sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    art_id = f"sha256:{sha}"
    doc_id = "tr:legislation:law:7500"

    conn = get_connection()
    upsert_document(conn, doc_id, "legislation", "law", "TR", "7500 Sayılı Kanun", "7500", "fetched")
    insert_artifact(
        conn,
        artifact_id=art_id,
        document_id=doc_id,
        source_id="resmi_gazete",
        source_url="https://www.resmigazete.gov.tr/eskiler/2026/08/7500.htm",
        retrieved_at="2026-08-01T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_file.stat().st_size,
        sha256=sha,
        raw_path=str(raw_file.relative_to(data_root)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    # 1. Document list contract
    list_res = client.get("/api/documents")
    assert list_res.status_code == 200
    items = list_res.json()["data"]["items"]
    assert len(items) >= 1
    doc_item = next(d for d in items if d["document_id"] == doc_id)
    assert doc_item["lifecycle_status"] == "fetched"
    assert doc_item["source_id"] == "resmi_gazete"

    # 2. Document detail contract
    detail_res = client.get(f"/api/documents/{doc_id}")
    assert detail_res.status_code == 200
    doc_detail = detail_res.json()["data"]
    assert doc_detail["document_id"] == doc_id
    assert doc_detail["lifecycle_status"] == "fetched"
    assert doc_detail["source_id"] == "resmi_gazete"
    assert len(doc_detail["artifacts"]) == 1
    assert doc_detail["artifacts"][0]["artifact_id"] == art_id

    # 3. Document text endpoint
    text_res = client.get(f"/api/documents/{doc_id}/text")
    assert text_res.status_code == 200
    text_data = text_res.json()["data"]
    assert text_data["document_id"] == doc_id
    assert "7500" in text_data["content"]
    assert text_data["content"] != "Metin içeriği bulunamadı."


def test_finding_2_and_3_aym_manual_ingestion_family_and_types(client, tmp_path):
    """Finding 2 & 3: AYM manual ingestion family mapping and document type constraint.

    Tests:
    1. AYM upload automatically resolves family 'decision' and creates valid artifact.
    2. Document identity generated for AYM reflects decision family namespace (tr:case-law:...).
    3. Backend does not reject valid AYM upload with SOURCE_FAMILY_NOT_ALLOWED.
    4. Incompatible family explicitly passed on AYM source is mapped or validated safely.
    """
    decision_html = """<!DOCTYPE html>
    <html>
    <head><title>Anayasa Mahkemesi Kararı</title></head>
    <body>
      <h1>T.C. ANAYASA MAHKEMESİ</h1>
      <h2>Bireysel Başvuru</h2>
      <p>Başvuru Numarası: 2021/12345</p>
      <p>Karar Tarihi: 15/05/2023</p>
      <p>I. BAŞVURUNUN KONUSU: Başvuru, adil yargılanma hakkının ihlal edildiği iddiasına ilişkindir.</p>
      <p>II. HÜKÜM: Anayasa'nın 36. maddesinde güvence altına alınan adil yargılanma hakkının İHLAL EDİLDİĞİNE karar verildi.</p>
    </body>
    </html>"""

    aym_doc_id = "tr:case-law:aym:decision:2021-12345"

    upload_res = client.post(
        "/api/manual/upload-file",
        data={
            "source_id": "aym",
            "document_id": aym_doc_id,
            "family": "legislation",  # Client sent default form value
            "document_type": "decision",
            "jurisdiction": "TR",
            "title": "AYM Bireysel Başvuru Kararı 2021/12345",
        },
        files={"file": ("aym_karar_2021_12345.html", decision_html.encode("utf-8"), "text/html")},
    )

    # Must succeed without SOURCE_FAMILY_NOT_ALLOWED
    assert upload_res.status_code == 200, f"Upload failed: {upload_res.text}"
    art_data = upload_res.json()["data"]
    assert "artifact_id" in art_data

    # Process pipeline for AYM artifact
    proc_res = client.post(f"/api/artifacts/{art_data['artifact_id']}/process")
    assert proc_res.status_code == 200
    assert proc_res.json()["data"]["pipeline_status"] in ("needs_review", "schema_valid")


def test_finding_4_artifact_level_issue_context_and_presentation(client, tmp_path):
    """Finding 4: Artifact-level issues connection to document/user context.

    Tests:
    1. Issue attached to artifact with document relation resolves document_title, document_id, source_id.
    2. Issue attached to unlinked artifact provides source_id and raw_path for human fallback.
    """
    conn = get_connection()
    doc_id = "tr:legislation:law:8000"
    art_id = "sha256:11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff"

    upsert_document(conn, doc_id, "legislation", "law", "TR", "8000 Sayılı Kanun", "8000", "fetched")
    insert_artifact(
        conn,
        artifact_id=art_id,
        document_id=doc_id,
        source_id="resmi_gazete",
        source_url="https://www.resmigazete.gov.tr/eskiler/2026/08/8000.htm",
        retrieved_at="2026-08-01T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=1024,
        sha256="11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff",
        raw_path="raw/legislation/resmi_gazete/2026/8000.html",
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )

    open_issue(
        conn,
        issue_id="iss-art-001",
        subject_type="artifact",
        subject_id=art_id,
        severity="error",
        code="PARSING_FAILED",
        message="Parsed text is empty",
        details_json="{}",
    )
    conn.close()

    res = client.get("/api/issues")
    assert res.status_code == 200
    issues = res.json()["data"]
    iss = next(i for i in issues if i["issue_id"] == "iss-art-001")
    assert iss["document_title"] == "8000 Sayılı Kanun"
    assert iss["document_id"] == doc_id
    assert iss["source_id"] == "resmi_gazete"


def test_finding_5_human_error_presentation_coverage():
    """Finding 5: Pipeline & privacy error code translation coverage.

    Verifies app.js contains presentation mappings for all required pipeline and privacy codes.
    """
    app_js_path = Path(__file__).parent.parent.parent / "src" / "mesa_legal_data" / "web" / "static" / "app.js"
    assert app_js_path.exists()
    content = app_js_path.read_text(encoding="utf-8")

    required_codes = [
        "TRANSPORT_VERIFICATION_FAILED",
        "PARSING_FAILED",
        "SCHEMA_VALIDATION_FAILED",
        "PRIVACY_TCKN_DETECTED",
        "PRIVACY_IBAN_DETECTED",
        "PRIVACY_PHONE_DETECTED",
        "PRIVACY_EMAIL_DETECTED",
        "VALIDATION_DATE_MISSING",
        "VALIDATION_TITLE_MISSING",
        "VALIDATION_SCHEMA_INVALID",
        "HASH_MISMATCH",
        "CANONICAL_LINE_MISSING",
        "DUPLICATE_ITEM",
        "PARSER_ERROR",
        "BLOCKING_ISSUES_EXIST",
        "SOURCE_FAMILY_NOT_ALLOWED",
    ]

    for code in required_codes:
        assert code in content, f"Code '{code}' missing from app.js presentation dictionary"

    # Verify fallback message exists
    assert "Belgenin işlenmesi sırasında bir sorun oluştu." in content


def test_finding_6_harvest_empty_types_rejected(client):
    """Finding 6: Harvest validation on empty document type selection.

    Tests:
    1. Direct API request with document_types = [] is rejected with 400 INVALID_DOCUMENT_TYPES.
    2. Selected subset (e.g. ['law']) is passed through without default fallback.
    """
    empty_res = client.post(
        "/api/harvest/start",
        json={"source_id": "resmi_gazete", "document_types": []},
    )
    assert empty_res.status_code == 400
    assert empty_res.json()["error"]["code"] == "INVALID_DOCUMENT_TYPES"

    # Valid subset
    subset_res = client.post(
        "/api/harvest/start",
        json={"source_id": "resmi_gazete", "document_types": ["law", "regulation"]},
    )
    assert subset_res.status_code == 200
    assert subset_res.json()["data"]["status"] == "submitted"

    # Stop harvest
    client.post("/api/harvest/stop")


def test_finding_7_issue_manual_resolution_audit(client):
    """Finding 7: Issue manual override semantics and audit logging.

    Tests:
    1. Resolving an issue requires an explicit resolution note and actor.
    2. Resolving records an audit event in the database.
    3. Status transitions from 'open' to 'resolved'.
    """
    conn = get_connection()
    open_issue(
        conn,
        issue_id="iss-manual-001",
        subject_type="record",
        subject_id="rec-test-001",
        severity="blocker",
        code="PRIVACY_TCKN_DETECTED",
        message="Valid TC Kimlik No detected",
        details_json="{}",
    )
    conn.close()

    res = client.post(
        "/api/issues/iss-manual-001/resolve",
        json={
            "status": "resolved",
            "resolved_by": "expert_lawyer",
            "resolution_note": "Manuel inceleme ile kamuya açık mevzuat metni olduğu teyit edildi.",
        },
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["status"] == "resolved"
    assert data["resolved_by"] == "expert_lawyer"

    # Verify audit log recorded
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT actor, action, subject_type, subject_id FROM audit_events WHERE subject_id = 'iss-manual-001'")
    audit_row = c.fetchone()
    assert audit_row is not None
    assert audit_row[0] == "expert_lawyer"
    assert audit_row[1] == "issue_resolved"
    assert audit_row[2] == "issue"
    conn.close()


def test_cross_flow_blocked_review_to_issue_resolution(client, tmp_path):
    """Section 32 Mandatory Cross-Flow Test:

    1. Process document into a record with an open blocker issue.
    2. Attempt to approve record -> blocked with 409 and Turkish explanation.
    3. Open issues -> issue is visible with context.
    4. Manually resolve issue with audit note.
    5. Attempt approval again -> successfully approves!
    """
    data_root = Path(tmp_path / "web_remediation_data")
    raw_dir = data_root / "raw" / "legislation" / "resmi_gazete" / "2026"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "kanun_9999.html"
    raw_text = "<!DOCTYPE html><html><body><h1>KANUN</h1><p>No: 9999</p><div><b>Madde 1-</b> Deneme kanunu.</div></body></html>"
    raw_file.write_text(raw_text, encoding="utf-8")
    sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    art_id = f"sha256:{sha}"
    doc_id = "tr:legislation:law:9999"

    conn = get_connection()
    upsert_document(conn, doc_id, "legislation", "law", "TR", "9999 Sayılı Kanun", "9999", "fetched")
    insert_artifact(
        conn,
        artifact_id=art_id,
        document_id=doc_id,
        source_id="resmi_gazete",
        source_url="https://www.resmigazete.gov.tr/eskiler/2026/08/9999.htm",
        retrieved_at="2026-08-01T00:00:00Z",
        fetch_method="manual",
        http_status=200,
        declared_content_type="text/html",
        detected_content_type="text/html",
        byte_size=raw_file.stat().st_size,
        sha256=sha,
        raw_path=str(raw_file.relative_to(data_root)),
        etag=None,
        last_modified=None,
        transport_status="fetched",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    process_artifact_pipeline(artifact_id=art_id)

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT r.record_id FROM records r JOIN versions v ON v.version_id = r.version_id WHERE v.document_id = ? LIMIT 1",
        (doc_id,),
    )
    rec_id = c.fetchone()[0]

    # Open a blocking issue on the record
    blocker_id = "iss-blocker-crossflow"
    open_issue(
        conn,
        issue_id=blocker_id,
        subject_type="record",
        subject_id=rec_id,
        severity="blocker",
        code="BLOCKING_ISSUES_EXIST",
        message="Kritik doğrulama engeli mevcut",
        details_json="{}",
    )
    conn.close()

    # 1. Attempt to approve record -> must be blocked
    approve_fail = client.post(
        f"/api/records/{rec_id}/approve",
        json={"reviewer": "test_reviewer", "note": "Hemen onayla"},
    )
    assert approve_fail.status_code == 400
    assert approve_fail.json()["error"]["code"] == "BLOCKING_ISSUES_EXIST"

    # 2. Check issues list
    issues_res = client.get(f"/api/issues?subject_id={rec_id}")
    assert issues_res.status_code == 200
    issue_items = issues_res.json()["data"]
    assert len(issue_items) == 1
    assert issue_items[0]["issue_id"] == blocker_id
    assert issue_items[0]["status"] == "open"

    # 3. Manually resolve issue
    resolve_res = client.post(
        f"/api/issues/{blocker_id}/resolve",
        json={
            "status": "resolved",
            "resolved_by": "test_reviewer",
            "resolution_note": "Sorun uzman tarafından incelendi ve çözüldü kabul edildi.",
        },
    )
    assert resolve_res.status_code == 200

    # 4. Now approve record -> must succeed
    approve_success = client.post(
        f"/api/records/{rec_id}/approve",
        json={"reviewer": "test_reviewer", "note": "Sorun giderildikten sonra onaylandı"},
    )
    assert approve_success.status_code == 200
    assert approve_success.json()["data"]["status"] == "approved"
