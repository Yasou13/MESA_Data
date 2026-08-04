import re

from pydantic import BaseModel, ConfigDict

from mesa_legal_data.parsers.text_normalizer import normalize_text


class ParsedArticle(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_number: str
    article_kind: str  # "standard", "additional", "temporary"
    heading: str | None = None
    text: str


class ParsedLegislation(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None = None
    number: str | None = None
    articles: list[ParsedArticle] = []


ARTICLE_PATTERN = re.compile(
    r"^(?P<kind>EK MADDE|GEÇİCİ MADDE|MADDE)\s+(?P<num>\d+|[A-ZÇĞİÖŞÜ]+)\s*[-–—:]?\s*(?P<heading>.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_legislation_text(text: str) -> ParsedLegislation:
    """
    Parses normalized legislation text into structured articles.
    """
    text = normalize_text(text)
    if not text:
        return ParsedLegislation()

    lines = text.split("\n")
    articles: list[ParsedArticle] = []

    current_kind: str | None = None
    current_num: str | None = None
    current_heading: str | None = None
    current_body_lines: list[str] = []

    def flush_current():
        nonlocal current_kind, current_num, current_heading, current_body_lines
        if current_num is not None:
            kind_str = "standard"
            if current_kind == "EK MADDE":
                kind_str = "additional"
            elif current_kind == "GEÇİCİ MADDE":
                kind_str = "temporary"

            art_text = "\n".join(current_body_lines).strip()
            if not art_text:
                art_text = current_heading or f"Madde {current_num}"

            articles.append(
                ParsedArticle(
                    article_number=current_num,
                    article_kind=kind_str,
                    heading=current_heading if current_heading else None,
                    text=art_text,
                )
            )
        current_kind = None
        current_num = None
        current_heading = None
        current_body_lines = []

    for line in lines:
        match = ARTICLE_PATTERN.match(line)
        if match:
            flush_current()
            raw_kind = match.group("kind").upper()
            num = match.group("num")
            heading_text = match.group("heading").strip()

            current_kind = raw_kind
            current_num = num
            current_heading = heading_text if heading_text else None
        else:
            if current_num is not None:
                current_body_lines.append(line)

    flush_current()
    return ParsedLegislation(articles=articles)
