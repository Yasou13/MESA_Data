import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from mesa_legal_data.canonical import write_canonical_part
from mesa_legal_data.catalog import (
    create_run,
    finish_run,
    get_artifact,
    get_connection,
    get_document,
    insert_record,
    insert_version,
    open_issue,
    transaction,
    update_artifact_transport_status,
    update_document_status,
)
from mesa_legal_data.config import load_settings
from mesa_legal_data.ids import (
    build_article_id,
    build_citation_id,
    build_decision_id,
    build_legislation_version_id,
)
from mesa_legal_data.parsers import (
    extract_citations,
    parse_decision_text,
    parse_html,
    parse_legislation_text,
    parse_pdf,
)
from mesa_legal_data.schema_validation import validate_record
from mesa_legal_data.validators import (
    scan_privacy_issues,
    validate_legal_metadata,
    validate_transport_integrity,
)


class InvalidStateTransition(Exception):
    pass


ALLOWED_TRANSITIONS = {
    "discovered": {"fetched", "failed"},
    "fetched": {"transport_verified", "failed"},
    "transport_verified": {"parsed", "failed"},
    "parsed": {"schema_valid", "failed"},
    "schema_valid": {"privacy_pending", "failed"},
    "privacy_pending": {"approved", "needs_review", "rejected"},
    "needs_review": {"approved", "rejected"},
    "approved": {"released", "superseded"},
    "released": {"revoked", "superseded"},
    "failed": set(),
    "rejected": set(),
    "revoked": set(),
    "superseded": set(),
}


def transition_state(current_state: str, new_state: str) -> str:
    if current_state not in ALLOWED_TRANSITIONS:
        raise InvalidStateTransition(f"Unknown current state: {current_state}")
    if new_state not in ALLOWED_TRANSITIONS[current_state]:
        raise InvalidStateTransition(f"Cannot transition from {current_state} to {new_state}")
    return new_state


def process_artifact_pipeline(
    artifact_id: str,
    raw_path_str: str | None = None,
    document_id: str | None = None,
    family: str | None = None,
    sha256: str | None = None,
    byte_size: int | None = None,
    detected_mime: str | None = None,
) -> str:
    """
    Orchestrates end-to-end processing of an artifact:
    Transport -> Parse -> Canonical Models -> JSON Schema & Metadata -> Privacy -> Canonical JSONL Write -> Catalog Version/Records
    """
    settings = load_settings()
    conn = get_connection()

    # Step 1: Create processing run
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(UTC).isoformat()
    create_run(
        conn=conn,
        run_id=run_id,
        command="mesa-data pipeline run",
        source_id="manual",
        code_version="0.1.0",
        config_sha256="config_sha256",
        input_json=json.dumps({"artifact_id": artifact_id}),
    )

    # Step 2: Fetch artifact and document details from catalog
    art_row = get_artifact(conn, artifact_id)
    if not art_row:
        finish_run(
            conn,
            run_id,
            "failed",
            json.dumps({}),
            error_summary=f"Artifact {artifact_id} not found",
        )
        conn.close()
        raise ValueError(f"Artifact {artifact_id} not found in catalog")

    doc_id = document_id or art_row["document_id"]
    doc_row = get_document(conn, doc_id) if doc_id else None
    fam = family or (doc_row["family"] if doc_row else "legislation")

    raw_path_rel = raw_path_str or art_row["raw_path"]
    full_path = settings.data_root_path / raw_path_rel
    expected_sha = sha256 or art_row["sha256"]
    expected_size = byte_size if byte_size is not None else art_row["byte_size"]
    mime = detected_mime or art_row["detected_content_type"]

    state = "fetched"
    issues_count = 0

    # Step 3: Transport Verification
    try:
        validate_transport_integrity(
            file_path=full_path,
            expected_sha256=expected_sha,
            expected_byte_size=expected_size,
            expected_content_type=mime,
        )
        update_artifact_transport_status(conn, artifact_id, "verified")
        state = transition_state(state, "transport_verified")
    except Exception as e:
        open_issue(
            conn,
            issue_id=f"iss-{uuid.uuid4().hex[:8]}",
            subject_type="artifact",
            subject_id=artifact_id,
            severity="blocker",
            code="TRANSPORT_VERIFICATION_FAILED",
            message=str(e),
            details_json=json.dumps({"raw_path": raw_path_rel}),
        )
        finish_run(conn, run_id, "failed", json.dumps({"issues": 1}), error_summary=str(e))
        conn.close()
        return "failed"

    # Step 4: Parse
    parsed_text = ""
    try:
        if "pdf" in mime:
            parsed_text = parse_pdf(full_path)
        else:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "html" in mime:
                parsed_text = parse_html(content)
            else:
                parsed_text = content

        if not parsed_text or not parsed_text.strip():
            raise ValueError("Parsed text is empty")

        state = transition_state(state, "parsed")
    except Exception as e:
        open_issue(
            conn,
            issue_id=f"iss-{uuid.uuid4().hex[:8]}",
            subject_type="artifact",
            subject_id=artifact_id,
            severity="blocker",
            code="PARSING_FAILED",
            message=str(e),
            details_json=json.dumps({"mime": mime}),
        )
        finish_run(conn, run_id, "failed", json.dumps({"issues": 1}), error_summary=str(e))
        conn.close()
        return "failed"

    # Step 5 & 6: Create Canonical Models, Validate JSON Schema & Metadata
    canonical_records: list[dict[str, Any]] = []
    version_id = build_legislation_version_id(doc_id or "tr:legislation:unknown", now_iso[:10], expected_sha)

    meta_dict: dict[str, Any] = {}
    if art_row and art_row.get("metadata_json"):
        try:
            meta_dict = json.loads(art_row["metadata_json"])
        except Exception:
            pass

    source_obj = {
        "source_id": art_row["source_id"],
        "source_url": art_row["source_url"],
        "retrieved_at": art_row["retrieved_at"],
        "artifact_sha256": art_row["sha256"],
        "artifact_path": art_row["raw_path"],
    }
    provenance_obj = {
        "parser_name": f"{fam}_parser",
        "parser_version": "1.0.0",
        "pipeline_run_id": run_id,
    }

    leg_count = 0
    art_count = 0
    dec_count = 0
    cit_count = 0

    try:
        if fam == "legislation":
            leg_parsed = parse_legislation_text(parsed_text)
            title = doc_row["title"] if doc_row and doc_row.get("title") else "Mevzuat Metni"
            num = doc_id.split(":")[-1] if doc_id else "0"
            num_match = re.search(r"\b(\d{1,8})\s+sayılı\b", title, re.IGNORECASE)
            if num_match:
                num = num_match.group(1)

            doc_type = None
            if doc_row and doc_row.get("document_type"):
                doc_type = str(doc_row["document_type"]).strip()
            elif doc_id and doc_id.startswith("tr:legislation:"):
                parts = doc_id.split(":")
                if len(parts) >= 3 and parts[2]:
                    doc_type = parts[2]

            if not doc_type:
                doc_type = "law"

            v_kind = "consolidated_snapshot"
            if art_row.get("source_id") == "resmi_gazete" or meta_dict.get("source_role") == "original_publication":
                v_kind = "original_publication"

            pub_info = None
            pub_d = meta_dict.get("publication_date")
            if pub_d:
                pub_info = {"date": str(pub_d)}

            leg_record = {
                "id": doc_id or f"tr:legislation:{doc_type}:0",
                "record_type": "legislation",
                "jurisdiction": "TR",
                "language": "tr",
                "legislation_type": doc_type,
                "number": num,
                "title": title,
                "short_title": None,
                "publication": pub_info,
                "status": "active",
                "version": {
                    "version_id": version_id,
                    "version_kind": v_kind,
                    "snapshot_date": now_iso[:10],
                    "effective_from": None,
                    "effective_to": None,
                },
                "full_text": parsed_text,
                "schema_version": "1.0.0",
                "created_at": now_iso,
                "source": source_obj,
                "provenance": provenance_obj,
            }
            validate_legal_metadata(leg_record)
            validate_record(leg_record)
            canonical_records.append(leg_record)
            leg_count += 1

            for a in leg_parsed.articles:
                art_id = build_article_id(str(leg_record["id"]), a.article_number, a.article_kind)
                art_record = {
                    "id": art_id,
                    "record_type": "article",
                    "legislation_id": leg_record["id"],
                    "legislation_version_id": version_id,
                    "article_number": a.article_number,
                    "article_kind": a.article_kind,
                    "heading": a.heading,
                    "text": a.text,
                    "structure": None,
                    "status": "active",
                    "effective_from": None,
                    "effective_to": None,
                    "source_span": None,
                    "schema_version": "1.0.0",
                    "created_at": now_iso,
                    "source": source_obj,
                    "provenance": provenance_obj,
                }
                validate_record(art_record)
                canonical_records.append(art_record)
                art_count += 1

            # Extract citations
            extracted_cits = extract_citations(parsed_text)
            for c in extracted_cits:
                c_id = build_citation_id(
                    str(leg_record["id"]),
                    c.char_start or 0,
                    c.char_end or 0,
                    c.target_legislation_id,
                )
                cit_record = {
                    "id": c_id,
                    "record_type": "citation",
                    "source_legislation_id": leg_record["id"],
                    "source_article_id": None,
                    "target_legislation_id": c.target_legislation_id,
                    "target_article_id": c.target_article_id,
                    "citation_type": c.citation_type,
                    "raw_text": c.raw_text,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "schema_version": "1.0.0",
                    "created_at": now_iso,
                    "source": source_obj,
                    "provenance": provenance_obj,
                }
                validate_record(cit_record)
                canonical_records.append(cit_record)
                cit_count += 1

        else:
            # Decision family
            dec_parsed = parse_decision_text(parsed_text)
            dec_id = build_decision_id(
                dec_parsed.court or "unknown",
                dec_parsed.chamber,
                dec_parsed.esas_no,
                dec_parsed.karar_no,
                expected_sha,
            )
            dec_record = {
                "id": dec_id,
                "record_type": "decision",
                "jurisdiction": "TR",
                "language": "tr",
                "court": dec_parsed.court,
                "chamber": dec_parsed.chamber,
                "esas_no": dec_parsed.esas_no,
                "karar_no": dec_parsed.karar_no,
                "decision_date": dec_parsed.decision_date,
                "summary": dec_parsed.summary,
                "text": parsed_text,
                "verdict": dec_parsed.verdict,
                "schema_version": "1.0.0",
                "created_at": now_iso,
                "source": source_obj,
                "provenance": provenance_obj,
            }
            validate_record(dec_record)
            canonical_records.append(dec_record)
            dec_count += 1

            extracted_cits = extract_citations(parsed_text)
            for c in extracted_cits:
                c_id = build_citation_id(dec_id, c.char_start or 0, c.char_end or 0, c.target_legislation_id)
                cit_record = {
                    "id": c_id,
                    "record_type": "citation",
                    "source_record_id": dec_id,
                    "target_legislation_id": c.target_legislation_id,
                    "target_article_id": c.target_article_id,
                    "raw_text": c.raw_text,
                    "source_span": {"char_start": c.char_start, "char_end": c.char_end},
                    "extraction_method": "deterministic_regex",
                    "validation_status": "validated",
                    "schema_version": "1.0.0",
                    "created_at": now_iso,
                    "source": source_obj,
                    "provenance": provenance_obj,
                }
                validate_record(cit_record)
                canonical_records.append(cit_record)
                cit_count += 1

        state = transition_state(state, "schema_valid")
    except Exception as e:
        open_issue(
            conn,
            issue_id=f"iss-{uuid.uuid4().hex[:8]}",
            subject_type="artifact",
            subject_id=artifact_id,
            severity="error",
            code="SCHEMA_VALIDATION_FAILED",
            message=str(e),
            details_json="{}",
        )
        finish_run(conn, run_id, "failed", json.dumps({"issues": 1}), error_summary=str(e))
        conn.close()
        return "failed"

    # Step 7: Privacy Scan
    state = transition_state(state, "privacy_pending")
    privacy_issues = scan_privacy_issues(parsed_text)

    final_status = "needs_review"
    privacy_status = "clean" if not privacy_issues else "flagged"

    for iss in privacy_issues:
        issues_count += 1
        open_issue(
            conn,
            issue_id=f"iss-{uuid.uuid4().hex[:8]}",
            subject_type="artifact",
            subject_id=artifact_id,
            severity=iss["severity"],
            code=iss["code"],
            message=iss["message"],
            details_json=json.dumps({"match_type": iss["match_type"], "masked": iss["masked"]}),
        )
        if iss["severity"] == "blocker":
            final_status = "rejected"

    # Step 8: Write Canonical JSONL Part Files
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    for r in canonical_records:
        rt = r["record_type"]
        records_by_type.setdefault(rt, []).append(r)

    canonical_locations = []
    for rt, r_list in records_by_type.items():
        locs = write_canonical_part(r_list, rt, run_id)
        canonical_locations.extend(locs)

    # Step 9: Atomic Catalog Write for Version & Records
    with transaction(conn):
        # Insert Version record
        first_loc = canonical_locations[0] if canonical_locations else None
        c_path = first_loc.relative_path if first_loc else ""
        c_sha = first_loc.record_sha256 if first_loc else expected_sha

        insert_version(
            conn=conn,
            version_id=version_id,
            document_id=doc_id or "tr:legislation:unknown",
            artifact_id=artifact_id,
            version_kind="consolidated_snapshot",
            snapshot_date=now_iso[:10],
            effective_from=None,
            effective_to=None,
            canonical_path=c_path,
            canonical_line=1,
            canonical_sha256=c_sha,
            parser_name=f"{fam}_parser",
            parser_version="1.0.0",
            schema_version="1.0.0",
            validation_status="valid",
            privacy_status=privacy_status,
            approval_status="pending",
        )

        for loc in canonical_locations:
            insert_record(
                conn=conn,
                record_id=loc.record_id,
                version_id=version_id,
                record_type=loc.record_type,
                canonical_path=loc.relative_path,
                canonical_line=loc.line_number,
                record_sha256=loc.record_sha256,
                validation_status="valid",
                approval_status="pending",
            )

        if doc_id:
            update_document_status(conn, doc_id, final_status, current_version_id=version_id)

    # Step 10: Finish Run with Real Counters
    counters = {
        "artifacts_processed": 1,
        "legislation_records": leg_count,
        "article_records": art_count,
        "decision_records": dec_count,
        "citation_records": cit_count,
        "issues": issues_count,
    }
    finish_run(conn, run_id, "succeeded", json.dumps(counters))
    conn.close()

    return final_status
