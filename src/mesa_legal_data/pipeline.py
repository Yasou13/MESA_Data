import json
import uuid
from pathlib import Path

from mesa_legal_data.catalog import (
    get_connection,
    insert_version,
    insert_record,
    open_issue,
    create_run,
    finish_run,
)
from mesa_legal_data.config import load_settings
from mesa_legal_data.parsers import (
    parse_html,
    parse_pdf,
    parse_legislation_text,
    parse_decision_text,
)
from mesa_legal_data.validators import (
    validate_transport_integrity,
    validate_legal_metadata,
    scan_privacy_issues,
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
    """
    Validates and transitions to the new state.
    Raises InvalidStateTransition if the transition is not allowed.
    """
    if current_state not in ALLOWED_TRANSITIONS:
        raise InvalidStateTransition(f"Unknown current state: {current_state}")

    if new_state not in ALLOWED_TRANSITIONS[current_state]:
        raise InvalidStateTransition(f"Cannot transition from {current_state} to {new_state}")

    return new_state


def process_artifact_pipeline(
    artifact_id: str,
    raw_path_str: str,
    document_id: str,
    family: str,
    sha256: str,
    byte_size: int,
    detected_mime: str,
) -> str:
    """
    Executes the full pipeline for an artifact:
    1. Transport Verification
    2. Parsing
    3. Legal Metadata & Schema Validation
    4. Privacy Scan
    Returns final status ('approved', 'needs_review', or 'rejected').
    """
    settings = load_settings()
    full_path = settings.data_root_path / raw_path_str
    conn = get_connection()

    state = "fetched"

    # Step 1: Transport Verification
    try:
        validate_transport_integrity(
            file_path=full_path,
            expected_sha256=sha256,
            expected_byte_size=byte_size,
            expected_content_type=detected_mime,
        )
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
            details_json=json.dumps({"raw_path": raw_path_str}),
        )
        conn.close()
        return "failed"

    # Step 2: Parsing
    parsed_text = ""
    try:
        if "pdf" in detected_mime:
            parsed_text = parse_pdf(full_path)
        else:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "html" in detected_mime:
                parsed_text = parse_html(content)
            else:
                parsed_text = content

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
            details_json=json.dumps({"mime": detected_mime}),
        )
        conn.close()
        return "failed"

    # Step 3: Schema & Legal Metadata Validation
    try:
        if family == "legislation":
            leg = parse_legislation_text(parsed_text)
            meta_dict = {
                "id": document_id,
                "record_type": "legislation",
                "jurisdiction": "TR",
                "title": f"Document {document_id}",
            }
            validate_legal_metadata(meta_dict)

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
        conn.close()
        return "failed"

    # Step 4: Privacy Scan
    state = transition_state(state, "privacy_pending")
    privacy_issues = scan_privacy_issues(parsed_text)

    final_status = "approved"
    for iss in privacy_issues:
        open_issue(
            conn,
            issue_id=f"iss-{uuid.uuid4().hex[:8]}",
            subject_type="artifact",
            subject_id=artifact_id,
            severity=iss["severity"],
            code=iss["code"],
            message=iss["message"],
            details_json=json.dumps({"match": iss["match"]}),
        )
        if iss["severity"] == "blocker":
            final_status = "rejected"
        elif iss["severity"] == "warning" and final_status != "rejected":
            final_status = "needs_review"

    final_state = transition_state(state, final_status)
    conn.close()
    return final_state
