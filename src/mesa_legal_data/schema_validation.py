import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]


class SchemaValidationError(Exception):
    pass


_SCHEMA_CACHE: dict[str, Draft202012Validator] = {}


def _get_validator_for_type(record_type: str) -> Draft202012Validator:
    if record_type in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[record_type]

    schemas_dir = Path(__file__).parent.parent.parent / "schemas"
    schema_file = schemas_dir / f"{record_type}.schema.json"

    if not schema_file.exists():
        raise SchemaValidationError(f"Schema file not found for record type '{record_type}': {schema_file}")

    try:
        with open(schema_file, "r", encoding="utf-8") as f:
            schema_data = json.load(f)
        validator = Draft202012Validator(schema_data)
        _SCHEMA_CACHE[record_type] = validator
        return validator
    except Exception as e:
        raise SchemaValidationError(f"Failed to load schema for '{record_type}': {e}") from e


def validate_record(record: dict[str, Any]) -> None:
    """
    Validates a canonical record dict against its Draft 2020-12 JSON Schema.
    Raises SchemaValidationError on failure.
    """
    if "record_type" not in record:
        raise SchemaValidationError("Record is missing required 'record_type' field")

    record_type = record["record_type"]
    validator = _get_validator_for_type(record_type)

    errors = list(validator.iter_errors(record))
    if errors:
        first_err = errors[0]
        path_str = ".".join(str(p) for p in first_err.absolute_path) or "root"
        msg = f"Schema validation error at '{path_str}': {first_err.message}"
        raise SchemaValidationError(msg)
