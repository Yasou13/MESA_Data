import hashlib
import re
from typing import Any


def is_valid_tc_kimlik(tc: str) -> bool:
    """
    Validates an 11-digit Turkish National ID (TC Kimlik No) using algorithm checksum.
    """
    if len(tc) != 11 or not tc.isdigit() or tc[0] == "0":
        return False

    digits = [int(d) for d in tc]
    d = digits

    odd_sum = d[0] + d[2] + d[4] + d[6] + d[8]
    even_sum = d[1] + d[3] + d[5] + d[7]

    digit10 = ((odd_sum * 7) - even_sum) % 10
    digit11 = sum(d[:10]) % 10

    return digit10 == d[9] and digit11 == d[10]


TC_PATTERN = re.compile(r"\b[1-9]\d{10}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?90\s*|0)?5\d{2}[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b")
IBAN_PATTERN = re.compile(r"\bTR\d{2}\s*(?:\d{4}\s*){5}\d{2}\b", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _hash_match(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def scan_privacy_issues(text: str) -> list[dict[str, Any]]:
    """
    Scans text for potential PII (TCKN, IBAN, Phone, Email).
    Returns list of issue dictionaries without storing raw PII.
    """
    if not text:
        return []

    issues: list[dict[str, Any]] = []

    # 1. TCKN Scan
    for match in TC_PATTERN.finditer(text):
        tc_candidate = match.group(0)
        if is_valid_tc_kimlik(tc_candidate):
            masked = f"{tc_candidate[:3]}******{tc_candidate[-2:]}"
            issues.append(
                {
                    "code": "PRIVACY_TCKN_DETECTED",
                    "severity": "blocker",
                    "message": f"Valid TC Kimlik No detected: {masked}",
                    "match_type": "TCKN",
                    "masked": masked,
                    "match_sha256": _hash_match(tc_candidate),
                }
            )

    # 2. IBAN Scan
    for match in IBAN_PATTERN.finditer(text):
        iban = match.group(0)
        clean_iban = re.sub(r"\s+", "", iban)
        masked = f"{clean_iban[:4]}****{clean_iban[-4:]}"
        issues.append(
            {
                "code": "PRIVACY_IBAN_DETECTED",
                "severity": "warning",
                "message": f"IBAN detected: {masked}",
                "match_type": "IBAN",
                "masked": masked,
                "match_sha256": _hash_match(iban),
            }
        )

    # 3. Phone Scan
    for match in PHONE_PATTERN.finditer(text):
        phone = match.group(0)
        masked = f"{phone[:3]}***{phone[-2:]}"
        issues.append(
            {
                "code": "PRIVACY_PHONE_DETECTED",
                "severity": "warning",
                "message": f"Phone number detected: {masked}",
                "match_type": "PHONE",
                "masked": masked,
                "match_sha256": _hash_match(phone),
            }
        )

    # 4. Email Scan
    for match in EMAIL_PATTERN.finditer(text):
        email = match.group(0)
        user, domain = email.split("@", 1)
        masked = f"{user[:1]}***@{domain}"
        issues.append(
            {
                "code": "PRIVACY_EMAIL_DETECTED",
                "severity": "info",
                "message": f"Email detected: {masked}",
                "match_type": "EMAIL",
                "masked": masked,
                "match_sha256": _hash_match(email),
            }
        )

    return issues
