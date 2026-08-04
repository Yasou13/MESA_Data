import re

from pydantic import BaseModel, ConfigDict

from mesa_legal_data.parsers.text_normalizer import normalize_text


class ParsedDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    court: str | None = None
    chamber: str | None = None
    esas_no: str | None = None
    karar_no: str | None = None
    decision_date: str | None = None
    summary: str | None = None
    text: str = ""
    verdict: str | None = None


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
    raw_date = tarih_match.group(1) if tarih_match else None
    decision_date = None

    if raw_date:
        parts = re.split(r"[./-]", raw_date)
        if len(parts) == 3:
            day, month, year = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            decision_date = f"{year}-{month}-{day}"
        else:
            decision_date = raw_date

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
