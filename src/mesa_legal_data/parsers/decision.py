import re
from typing import Optional
from pydantic import BaseModel, ConfigDict

from mesa_legal_data.parsers.text_normalizer import normalize_text


class ParsedDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    court: Optional[str] = None
    chamber: Optional[str] = None
    esas_no: Optional[str] = None
    karar_no: Optional[str] = None
    decision_date: Optional[str] = None
    summary: Optional[str] = None
    text: str = ""
    verdict: Optional[str] = None


ESAS_NO_PATTERN = re.compile(r"Esas\s*No\s*[:\s]*([0-9]{4}\s*/\s*[0-9]+)", re.IGNORECASE)
KARAR_NO_PATTERN = re.compile(r"Karar\s*No\s*[:\s]*([0-9]{4}\s*/\s*[0-9]+)", re.IGNORECASE)
KARAR_TARIHI_PATTERN = re.compile(r"Karar\s*Tarihi\s*[:\s]*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{4})", re.IGNORECASE)


def parse_decision_text(text: str) -> ParsedDecision:
    """
    Parses normalized court decision text into structured metadata and body.
    """
    text = normalize_text(text)
    if not text:
        return ParsedDecision()

    esas_match = ESAS_NO_PATTERN.search(text)
    karar_match = KARAR_NO_PATTERN.search(text)
    tarih_match = KARAR_TARIHI_PATTERN.search(text)

    esas_no = esas_match.group(1).replace(" ", "") if esas_match else None
    karar_no = karar_match.group(1).replace(" ", "") if karar_match else None
    decision_date = tarih_match.group(1) if tarih_match else None

    # Detect court/chamber from first few lines
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    court = None
    chamber = None

    if lines:
        first_line = lines[0].upper()
        if "YARGITAY" in first_line:
            court = "YARGITAY"
            chamber = first_line.replace("YARGITAY", "").strip()
        elif "ANAYASA MAHKEMESİ" in first_line or "AYM" in first_line:
            court = "ANAYASA MAHKEMESİ"
        elif "DANIŞTAY" in first_line:
            court = "DANIŞTAY"

    return ParsedDecision(
        court=court,
        chamber=chamber,
        esas_no=esas_no,
        karar_no=karar_no,
        decision_date=decision_date,
        text=text,
    )
