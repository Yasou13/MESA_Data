import json
from pathlib import Path

import pytest

from mesa_legal_data.catalog import get_connection, get_db_path, insert_artifact, migrate, upsert_document
from mesa_legal_data.config import load_settings
from mesa_legal_data.pipeline import process_artifact_pipeline


@pytest.mark.parametrize(
    "doc_type",
    [
        "law",
        "regulation",
        "communique",
        "presidential_decree",
        "presidential_decision",
    ],
)
def test_canonical_document_type_propagation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, doc_type: str) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    raw_dir = data_root / "raw" / "resmi_gazete"
    raw_dir.mkdir(parents=True)

    dummy_raw = raw_dir / f"test_{doc_type}.txt"
    dummy_text = f"MADDE 1 - Bu {doc_type} test metnidir."
    dummy_raw.write_text(dummy_text, encoding="utf-8")

    import hashlib

    sha256 = hashlib.sha256(dummy_text.encode("utf-8")).hexdigest()

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    load_settings()
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(db_path=db_path)

    conn = get_connection(db_path)
    doc_id = f"tr:legislation:{doc_type}:100"
    art_id = f"art-{doc_type}-1"

    upsert_document(
        conn,
        document_id=doc_id,
        family="legislation",
        document_type=doc_type,
        jurisdiction="TR",
        title=f"Test {doc_type.title()}",
        stable_key=doc_id,
        lifecycle_status="active",
    )
    from datetime import UTC, datetime

    insert_artifact(
        conn,
        artifact_id=art_id,
        document_id=doc_id,
        source_id="resmi_gazete",
        source_url=f"https://resmigazete.gov.tr/{doc_type}.htm",
        retrieved_at=datetime.now(UTC).isoformat(),
        fetch_method="direct",
        http_status=200,
        declared_content_type="text/plain",
        detected_content_type="text/plain",
        byte_size=len(dummy_text.encode("utf-8")),
        sha256=sha256,
        raw_path=str(dummy_raw.relative_to(data_root)),
        etag=None,
        last_modified=None,
        transport_status="unverified",
        error_code=None,
        metadata_json="{}",
    )
    conn.close()

    result_status = process_artifact_pipeline(art_id)
    assert result_status in ("needs_review", "approved")

    # Find canonical JSONL file and verify legislation_type
    canonical_files = list((data_root / "canonical").glob("**/*.jsonl"))
    assert len(canonical_files) > 0

    found_type = None
    for c_file in canonical_files:
        with open(c_file, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("record_type") == "legislation":
                    found_type = rec.get("legislation_type")
                    break

    assert found_type == doc_type
