import hashlib
import json

from mesa_legal_data.catalog import (
    get_connection,
    get_db_path,
    get_document,
    get_version_for_artifact,
    insert_artifact,
    migrate,
    upsert_document,
)
from mesa_legal_data.pipeline import process_artifact_pipeline


def _ingest_law(tmp_path, *, document_id: str, artifact_id: str, body: str, metadata: dict) -> dict:
    migrate(None, get_db_path())
    raw = f"<html><body><h1>TEST KANUNU</h1><p><b>MADDE 1-</b> {body}</p></body></html>".encode()
    raw_path = tmp_path / "raw" / f"{artifact_id}.html"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    conn = get_connection()
    upsert_document(conn, document_id, "legislation", "law", "TR", "Test Kanunu", document_id, "fetched")
    insert_artifact(
        conn,
        artifact_id,
        document_id,
        "mevzuat",
        f"https://example.test/{artifact_id}.html",
        "2026-10-11T12:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        len(raw),
        hashlib.sha256(raw).hexdigest(),
        str(raw_path.relative_to(tmp_path)),
        None,
        None,
        "fetched",
        None,
        json.dumps(metadata),
    )
    conn.close()
    process_artifact_pipeline(artifact_id)
    conn = get_connection()
    version = get_version_for_artifact(conn, artifact_id)
    conn.close()
    assert version is not None
    return version


def test_acquisition_time_is_not_used_as_legal_snapshot_date(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    version = _ingest_law(
        tmp_path,
        document_id="tr:legislation:law:9998",
        artifact_id="art-no-legal-date",
        body="Hukuk.",
        metadata={"source_role": "consolidated_snapshot"},
    )
    assert version["snapshot_date"] == "unknown-date"
    assert version["quality_status"] == "REVIEW"
    conn = get_connection()
    assert (
        conn.execute(
            "SELECT count(*) FROM validation_issues WHERE version_id = ? AND code = 'LEGAL_DATE_MISSING'",
            (version["version_id"],),
        ).fetchone()[0]
        == 1
    )
    conn.close()


def test_declared_effective_interval_is_preserved_and_validated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    version = _ingest_law(
        tmp_path,
        document_id="tr:legislation:law:9997",
        artifact_id="art-effective-interval",
        body="Hukuk.",
        metadata={
            "source_role": "original_publication",
            "publication_date": "2025-01-01",
            "effective_from": "2025-02-01",
            "effective_to": "2026-01-31",
        },
    )
    assert version["effective_from"] == "2025-02-01"
    assert version["effective_to"] == "2026-01-31"


def test_contradictory_declared_effective_interval_requires_review(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    version = _ingest_law(
        tmp_path,
        document_id="tr:legislation:law:9996",
        artifact_id="art-invalid-effective-interval",
        body="Hukuk.",
        metadata={
            "publication_date": "2025-01-01",
            "effective_from": "2026-02-01",
            "effective_to": "2026-01-31",
        },
    )
    assert version["quality_status"] == "REVIEW"
    conn = get_connection()
    assert (
        conn.execute(
            "SELECT count(*) FROM validation_issues WHERE version_id = ? AND code = 'EFFECTIVE_INTERVAL_INVALID'",
            (version["version_id"],),
        ).fetchone()[0]
        == 1
    )
    conn.close()


def test_future_effective_version_does_not_replace_active_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    document_id = "tr:legislation:law:future-guard"
    active = _ingest_law(
        tmp_path,
        document_id=document_id,
        artifact_id="active-version",
        body="Bugün yürürlükte.",
        metadata={"publication_date": "2025-01-01", "effective_from": "2025-01-01"},
    )
    _ingest_law(
        tmp_path,
        document_id=document_id,
        artifact_id="future-version",
        body="Gelecekte yürürlüğe girecek.",
        metadata={"publication_date": "2026-09-01", "effective_from": "2027-01-01"},
    )
    conn = get_connection()
    assert get_document(conn, document_id)["current_version_id"] == active["version_id"]
    conn.close()


def test_overlapping_bounded_effective_intervals_force_review(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    document_id = "tr:legislation:law:interval-conflict"
    first = _ingest_law(
        tmp_path,
        document_id=document_id,
        artifact_id="interval-a",
        body="Birinci içerik.",
        metadata={
            "publication_date": "2025-01-01",
            "effective_from": "2025-01-01",
            "effective_to": "2027-01-31",
        },
    )
    second = _ingest_law(
        tmp_path,
        document_id=document_id,
        artifact_id="interval-b",
        body="Çelişkili içerik.",
        metadata={
            "publication_date": "2026-01-01",
            "effective_from": "2026-01-01",
            "effective_to": "2028-01-31",
        },
    )
    conn = get_connection()
    rows = conn.execute(
        "SELECT version_id, approval_status, quality_status FROM versions WHERE version_id IN (?, ?) ORDER BY version_id",
        (first["version_id"], second["version_id"]),
    ).fetchall()
    assert all(row[1:] == ("pending", "REVIEW") for row in rows)
    assert (
        conn.execute(
            "SELECT count(*) FROM validation_issues WHERE code = 'VERSION_EFFECTIVE_INTERVAL_AMBIGUITY' AND status = 'open'"
        ).fetchone()[0]
        == 2
    )
    conn.close()


def test_header_only_legislation_cannot_pass_quality_gate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    version = _ingest_law(
        tmp_path,
        document_id="tr:legislation:law:header-only",
        artifact_id="header-only",
        body="",
        metadata={"publication_date": "2026-01-01"},
    )
    assert version["quality_status"] == "BLOCK"
