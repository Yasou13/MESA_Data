import pytest

from mesa_legal_data.schema_validation import SchemaValidationError, validate_record


def test_schema_validation_legislation_valid():
    valid_leg = {
        "id": "tr:legislation:law:4721",
        "record_type": "legislation",
        "jurisdiction": "TR",
        "language": "tr",
        "legislation_type": "law",
        "number": "4721",
        "title": "Türk Medeni Kanunu",
        "short_title": "TMK",
        "publication": None,
        "status": "active",
        "version": {
            "version_id": "tr:legislation:law:4721:version:2026-08-05:abcdef12",
            "version_kind": "consolidated_snapshot",
            "snapshot_date": "2026-08-05",
            "effective_from": None,
            "effective_to": None,
        },
        "full_text": "Örnek metin",
        "schema_version": "1.0.0",
        "created_at": "2026-08-05T01:00:00Z",
        "source": {
            "source_id": "mevzuat",
            "source_url": "https://www.mevzuat.gov.tr/1",
            "retrieved_at": "2026-08-05T01:00:00Z",
            "artifact_sha256": "58de994c36ae00e6dc86c00b886c808d7bee1a2306b9ac35bf8aec9e8d297d1f",
            "artifact_path": "raw/test.pdf",
        },
        "provenance": {
            "parser_name": "legislation_parser",
            "parser_version": "1.0.0",
            "pipeline_run_id": "run-123",
        },
    }
    validate_record(valid_leg)


def test_schema_validation_missing_required():
    invalid_leg = {
        "id": "tr:legislation:law:4721",
        "record_type": "legislation",
    }
    with pytest.raises(SchemaValidationError):
        validate_record(invalid_leg)


def test_schema_validation_unknown_property():
    invalid_leg = {
        "id": "tr:legislation:law:4721",
        "record_type": "legislation",
        "unknown_field": 123,
    }
    with pytest.raises(SchemaValidationError):
        validate_record(invalid_leg)
