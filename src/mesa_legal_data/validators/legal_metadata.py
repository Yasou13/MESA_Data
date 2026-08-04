import re
from datetime import datetime


class LegalMetadataValidationError(Exception):
    pass


DOC_ID_PATTERN = re.compile(r"^tr:(legislation|case-law):[a-z0-9_-]+:[a-z0-9_:-]+$", re.IGNORECASE)


def validate_legal_metadata(record: dict) -> bool:
    """
    Validates legal metadata rules for canonical records.
    """
    record_type = record.get("record_type")
    doc_id = record.get("id")

    if not doc_id or not DOC_ID_PATTERN.match(doc_id):
        raise LegalMetadataValidationError(f"Invalid document ID format: {doc_id}")

    if record.get("jurisdiction") != "TR":
        raise LegalMetadataValidationError(f"Invalid jurisdiction: {record.get('jurisdiction')}")

    if record_type == "legislation":
        title = record.get("title")
        if not title or not isinstance(title, str) or not title.strip():
            raise LegalMetadataValidationError("Legislation must have a non-empty title")

        publication = record.get("publication")
        if publication and publication.get("date"):
            pub_date = publication.get("date")
            try:
                datetime.strptime(pub_date, "%Y-%m-%d")
            except ValueError:
                raise LegalMetadataValidationError(f"Invalid publication date format: {pub_date}")

    elif record_type == "decision":
        if not record.get("court"):
            raise LegalMetadataValidationError("Decision must specify a court")

        dec_date = record.get("decision_date")
        if dec_date:
            # Accepts YYYY-MM-DD or DD.MM.YYYY
            try:
                if "." in dec_date:
                    datetime.strptime(dec_date, "%d.%m.%Y")
                else:
                    datetime.strptime(dec_date, "%Y-%m-%d")
            except ValueError:
                raise LegalMetadataValidationError(f"Invalid decision date format: {dec_date}")

    return True
