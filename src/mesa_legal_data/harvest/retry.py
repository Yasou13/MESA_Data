from datetime import UTC, datetime, timedelta

PERMANENT_ERROR_CODES = {
    "SOURCE_DISABLED",
    "SOURCE_NOT_FOUND",
    "SOURCE_HOST_NOT_ALLOWED",
    "SOURCE_FAMILY_NOT_ALLOWED",
    "SOURCE_CONTENT_TYPE_NOT_ALLOWED",
    "FILE_TOO_LARGE",
    "PRIVATE_IP_NOT_ALLOWED",
    "HTTP_404",
    "HTTP_401",
    "HTTP_403",
    "DOCUMENT_TYPE_AMBIGUOUS",
    "PARSING_FAILED",
    "SCHEMA_VALIDATION_FAILED",
    "EMPTY_TEXT",
}

BACKOFF_DELAYS = [
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
]


def is_permanent_error(error_code: str | None) -> bool:
    if not error_code:
        return False
    return error_code in PERMANENT_ERROR_CODES


def calculate_next_retry(attempts: int, error_code: str | None, max_attempts: int = 5) -> tuple[str | None, bool]:
    """
    Returns (next_retry_at_iso_str | None, should_retry_bool).
    """
    if is_permanent_error(error_code):
        return None, False

    if attempts >= max_attempts:
        return None, False

    idx = min(max(0, attempts - 1), len(BACKOFF_DELAYS) - 1)
    delay = BACKOFF_DELAYS[idx]
    next_time = datetime.now(UTC) + delay
    return next_time.isoformat(), True
