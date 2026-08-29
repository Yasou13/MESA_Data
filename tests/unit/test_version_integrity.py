import hashlib
import json
from pathlib import Path

import pytest

from mesa_legal_data.catalog import (
    approve_version_streaming,
    get_connection,
    get_db_path,
    get_record,
    get_version,
    insert_artifact,
    iter_records_for_release,
    migrate,
    upsert_document,
    upsert_source,
)
from mesa_legal_data.pipeline import process_artifact_pipeline


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)
    return tmp_path


def create_sample_artifact(
    tmp_path: Path,
    filename: str,
    content: str,
    source_id: str = "mevzuat",
    publication_date: str = "2026-05-10",
) -> tuple[str, str, str]:
    raw_dir = tmp_path / "raw" / "legislation" / source_id / "2026"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / filename
    raw_bytes = content.encode("utf-8")
    raw_file.write_bytes(raw_bytes)
    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    rel_path = str(raw_file.relative_to(tmp_path))
    art_id = f"art-{sha256[:12]}"

    conn = get_connection()
    upsert_source(conn, source_id, "Official Source", "Authority", "https://example.com")
    insert_artifact(
        conn,
        art_id,
        None,
        source_id,
        f"https://example.com/{filename}",
        f"{publication_date}T10:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(raw_bytes),
        sha256,
        rel_path,
        None,
        None,
        "fetched",
        None,
        json.dumps({"publication_date": publication_date, "source_role": "consolidated_snapshot"}),
    )
    conn.close()
    return art_id, sha256, rel_path


def test_same_artifact_twice_idempotency_and_no_duplicates(test_env):
    """
    Processing the exact same artifact on different days or multiple times:
    - Must produce exactly one logical version
    - Must not duplicate record instances
    - Must preserve revision number
    """
    html_content = """<!DOCTYPE html>
    <html>
    <head><title>6698 Sayılı Kanun</title></head>
    <body>
    <h1>KİŞİSEL VERİLERİN KORUNMASI KANUNU</h1>
    <p><b>MADDE 1-</b> Bu Kanunun amacı, kişisel verilerin işlenmesinde...</p>
    <p><b>MADDE 9-</b> Kişisel veriler, ilgili kişinin açık rızası olmaksızın yurt dışına aktarılamaz.</p>
    </body>
    </html>"""

    art_id, sha256, rel_path = create_sample_artifact(test_env, "kvkk_v1.html", html_content)
    doc_id = "tr:legislation:law:6698"

    conn = get_connection()
    upsert_document(conn, doc_id, "legislation", "law", "TR", "6698 Sayılı Kanun", "stable-6698", "fetched")
    conn.close()

    # First pipeline run
    status1 = process_artifact_pipeline(artifact_id=art_id, document_id=doc_id)
    assert status1 == "needs_review"

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT count(*) FROM versions WHERE document_id = ?", (doc_id,))
    v_count_1 = c.fetchone()[0]
    assert v_count_1 == 1

    c.execute("SELECT version_id, revision_number, version_kind FROM versions WHERE document_id = ?", (doc_id,))
    ver_row_1 = c.fetchone()
    v1_id = ver_row_1[0]
    assert ver_row_1[1] == 1  # revision_number == 1
    assert ver_row_1[2] == "consolidated_snapshot"

    c.execute("SELECT count(*) FROM records WHERE version_id = ?", (v1_id,))
    records_count_1 = c.fetchone()[0]
    assert records_count_1 >= 3  # legislation + articles + citations

    # Approve version 1
    approve_version_streaming(conn, version_id=v1_id, reviewer="operator-test")
    v1_after_approval = get_version(conn, v1_id)
    assert v1_after_approval["approval_status"] == "approved"

    # Second pipeline run on the SAME artifact (e.g. daily reprocessing)
    before_reprocess = get_version(conn, v1_id)
    c.execute(
        "SELECT record_id, canonical_path, record_sha256 FROM records WHERE version_id = ? ORDER BY record_id",
        (v1_id,),
    )
    record_evidence_before = c.fetchall()

    status2 = process_artifact_pipeline(artifact_id=art_id, document_id=doc_id)
    assert status2 == "approved"

    # Verify no new fake version was created
    c.execute("SELECT count(*) FROM versions WHERE document_id = ?", (doc_id,))
    v_count_2 = c.fetchone()[0]
    assert v_count_2 == 1

    # Verify record count did not multiply
    c.execute("SELECT count(*) FROM records WHERE version_id = ?", (v1_id,))
    records_count_2 = c.fetchone()[0]
    assert records_count_2 == records_count_1

    # Verify approval status was preserved across reprocessing
    v1_after_reprocess = get_version(conn, v1_id)
    assert v1_after_reprocess["approval_status"] == "approved"
    assert v1_after_reprocess["revision_number"] == 1
    assert v1_after_reprocess["canonical_path"] == before_reprocess["canonical_path"]
    assert v1_after_reprocess["canonical_sha256"] == before_reprocess["canonical_sha256"]
    c.execute(
        "SELECT record_id, canonical_path, record_sha256 FROM records WHERE version_id = ? ORDER BY record_id",
        (v1_id,),
    )
    assert c.fetchall() == record_evidence_before
    conn.close()


def test_two_real_versions_same_document_isolation(test_env):
    """
    Same document with two distinct versions:
    - Both versions survive immutably
    - Logical Article 9 has two version-specific record instances
    - Version B insertion does NOT overwrite Version A records
    - Revision number sequences sequentially: Version 1 -> rev 1, Version 2 -> rev 2
    """
    doc_id = "tr:legislation:law:6698"
    conn = get_connection()
    upsert_document(conn, doc_id, "legislation", "law", "TR", "6698 Sayılı Kanun", "stable-6698", "fetched")
    conn.close()

    # Version A
    content_v1 = """<!DOCTYPE html><html><body>
    <h1>KİŞİSEL VERİLERİN KORUNMASI KANUNU</h1>
    <p><b>MADDE 1-</b> Amaç metni v1.</p>
    <p><b>MADDE 9-</b> Yurt dışına aktarım orijinal metin 2016.</p>
    </body></html>"""
    art_id_1, _, _ = create_sample_artifact(test_env, "kvkk_2016.html", content_v1, publication_date="2016-04-07")
    process_artifact_pipeline(artifact_id=art_id_1, document_id=doc_id)

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT version_id, revision_number FROM versions WHERE document_id = ? ORDER BY revision_number ASC", (doc_id,)
    )
    v1_row = c.fetchone()
    v1_id = v1_row[0]
    assert v1_row[1] == 1

    # Approve Version A
    approve_version_streaming(conn, version_id=v1_id, reviewer="operator-1")

    # Version B (Amended Article 9 in 2024)
    content_v2 = """<!DOCTYPE html><html><body>
    <h1>KİŞİSEL VERİLERİN KORUNMASI KANUNU</h1>
    <p><b>MADDE 1-</b> Amaç metni v1.</p>
    <p><b>MADDE 9-</b> Yurt dışına aktarım güncellenmiş 2024 standard sözleşme metni.</p>
    </body></html>"""
    raw_dir = test_env / "raw" / "legislation" / "mevzuat" / "2026"
    raw_file_2 = raw_dir / "kvkk_2024.html"
    raw_bytes_2 = content_v2.encode("utf-8")
    raw_file_2.write_bytes(raw_bytes_2)
    sha2 = hashlib.sha256(raw_bytes_2).hexdigest()
    art_id_2 = f"art-{sha2[:12]}"
    insert_artifact(
        conn,
        art_id_2,
        doc_id,
        "mevzuat",
        "https://example.com/kvkk_2024.html",
        "2026-08-01T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(raw_bytes_2),
        sha2,
        str(raw_file_2.relative_to(test_env)),
        None,
        None,
        "fetched",
        None,
        json.dumps({"publication_date": "2024-03-12", "source_role": "consolidated_snapshot"}),
    )
    conn.close()

    process_artifact_pipeline(artifact_id=art_id_2, document_id=doc_id)

    conn = get_connection()
    c = conn.cursor()

    # Both versions survive
    c.execute(
        "SELECT version_id, revision_number, supersedes_version_id FROM versions WHERE document_id = ? ORDER BY revision_number ASC",
        (doc_id,),
    )
    v_rows = c.fetchall()
    assert len(v_rows) == 2

    v1_id, v1_rev, v1_super = v_rows[0]
    v2_id, v2_rev, v2_super = v_rows[1]

    assert v1_rev == 1
    assert v2_rev == 2
    assert v2_super is None  # No source provenance explicitly identified a predecessor.

    # Check Article 9 in both versions
    logical_art9_id = "tr:legislation:law:6698:article:9"

    # Version A record instance
    rec_v1 = get_record(conn, logical_art9_id, version_id=v1_id)
    assert rec_v1 is not None
    assert rec_v1["version_id"] == v1_id
    assert rec_v1["approval_status"] == "approved"

    # Version B record instance
    rec_v2 = get_record(conn, logical_art9_id, version_id=v2_id)
    assert rec_v2 is not None
    assert rec_v2["version_id"] == v2_id
    assert rec_v2["approval_status"] == "pending"
    assert rec_v1["record_sha256"] != rec_v2["record_sha256"]  # Content changed

    # When both versions are approved, a release selects only the latest eligible
    # physical version and does not accidentally re-release Version A.
    approve_version_streaming(conn, version_id=v2_id, reviewer="operator-2")
    release_refs = list(iter_records_for_release(conn))
    assert release_refs
    assert {ref.version_id for ref in release_refs} == {v2_id}

    # Version C has the same source date as B but distinct source content. It is
    # a real third version, not an overwrite or a fabricated predecessor link.
    content_v3 = """<!DOCTYPE html><html><body>
    <h1>KİŞİSEL VERİLERİN KORUNMASI KANUNU</h1>
    <p><b>MADDE 1-</b> Amaç metni v1.</p>
    <p><b>MADDE 9-</b> Aynı gün yayımlanan düzeltilmiş üçüncü kaynak metni.</p>
    </body></html>"""
    raw_file_3 = raw_dir / "kvkk_2024_correction.html"
    raw_bytes_3 = content_v3.encode("utf-8")
    raw_file_3.write_bytes(raw_bytes_3)
    sha3 = hashlib.sha256(raw_bytes_3).hexdigest()
    art_id_3 = f"art-{sha3[:12]}"
    insert_artifact(
        conn,
        art_id_3,
        doc_id,
        "mevzuat",
        "https://example.com/kvkk_2024_correction.html",
        "2026-08-02T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(raw_bytes_3),
        sha3,
        str(raw_file_3.relative_to(test_env)),
        None,
        None,
        "fetched",
        None,
        json.dumps({"publication_date": "2024-03-12", "source_role": "consolidated_snapshot"}),
    )
    conn.close()

    process_artifact_pipeline(artifact_id=art_id_3, document_id=doc_id)
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT version_id, revision_number, snapshot_date, supersedes_version_id FROM versions WHERE document_id = ? ORDER BY revision_number",
        (doc_id,),
    )
    three_versions = c.fetchall()
    assert len(three_versions) == 3
    assert [row[1] for row in three_versions] == [1, 2, 3]
    assert three_versions[1][2] == three_versions[2][2] == "2024-03-12"
    assert three_versions[2][3] is None
    assert get_record(conn, logical_art9_id, version_id=v1_id)["record_sha256"] == rec_v1["record_sha256"]
    assert get_record(conn, logical_art9_id, version_id=v2_id)["record_sha256"] == rec_v2["record_sha256"]

    conn.close()


def test_version_kind_resmi_gazete_is_original_publication(test_env):
    """
    Test that source resmi_gazete or source_role original_publication
    is authoritatively set to original_publication in catalog versions.
    """
    html_content = """<!DOCTYPE html><html><body>
    <h1>7500 SAYILI KANUN</h1>
    <p><b>MADDE 1-</b> Resmî Gazete ilk yayım metni.</p>
    </body></html>"""
    art_id, _, _ = create_sample_artifact(test_env, "rg_law.html", html_content, source_id="resmi_gazete")
    doc_id = "tr:legislation:law:7500"

    conn = get_connection()
    upsert_document(conn, doc_id, "legislation", "law", "TR", "7500 Sayılı Kanun", "stable-7500", "fetched")
    conn.close()

    process_artifact_pipeline(artifact_id=art_id, document_id=doc_id)

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT version_kind FROM versions WHERE document_id = ?", (doc_id,))
    v_kind = c.fetchone()[0]
    assert v_kind == "original_publication"
    conn.close()
