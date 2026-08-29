import re

from pydantic import BaseModel, ConfigDict

from mesa_legal_data.parsers.text_normalizer import normalize_text

PARSER_NAME = "legislation_parser"
PARSER_VERSION = "1.0.0"


class ParsedArticle(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_number: str
    article_kind: str  # "standard", "additional", "temporary"
    heading: str | None = None
    text: str
    char_start: int | None = None
    char_end: int | None = None
    ordinal: int | None = None


class ParsedLegislation(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str | None = None
    number: str | None = None
    articles: list[ParsedArticle] = []


ARTICLE_PATTERN = re.compile(
    r"^(?P<kind>EK MADDE|GEÇİCİ MADDE|MADDE)\s+(?P<num>\d+|[A-ZÇĞİÖŞÜ]+)\s*[-–—:]?\s*(?P<heading>.*)$",
    re.IGNORECASE | re.MULTILINE,
)

NON_ARTICLE_BOUNDARY_PATTERN = re.compile(
    r"^(?:(?:BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|BEŞİNCİ|ALTINCI|YEDİNCİ|SEKİZİNCİ|DOKUZUNCU|ONUNCU)\s+(?:KISIM|BÖLÜM|AYIRIM)|(?:KISIM|BÖLÜM|AYIRIM)\s+[A-ZÇĞİÖŞÜ0-9]+|EK\s+(?:CETVEL|LİSTE|TABLO)|EK-\d+|EK\s+MADDE\b)",
    re.IGNORECASE,
)


def parse_legislation_text(text: str, auto_normalize: bool = True) -> ParsedLegislation:
    """
    Parses normalized legislation text into structured articles with exact source spans.
    Invariant: text[char_start:char_end] contains the article text in canonical coordinates.
    """
    if auto_normalize:
        text = normalize_text(text)
    if not text:
        return ParsedLegislation()

    matches = list(ARTICLE_PATTERN.finditer(text))
    if not matches:
        return ParsedLegislation()

    articles: list[ParsedArticle] = []

    for idx, match in enumerate(matches, start=1):
        raw_kind = match.group("kind").upper()
        num = match.group("num")
        heading_text = match.group("heading").strip()
        heading = heading_text if heading_text else None

        kind_str = "standard"
        if raw_kind == "EK MADDE":
            kind_str = "additional"
        elif raw_kind == "GEÇİCİ MADDE":
            kind_str = "temporary"

        match_start = match.start()
        next_match_start = matches[idx].start() if idx < len(matches) else len(text)

        article_block = text[match_start:next_match_start]

        # Scan for structural boundary inside block (e.g. KISIM / BÖLÜM / EK CETVEL)
        lines = article_block.split("\n")
        body_lines: list[str] = []
        effective_block_len = 0
        current_offset = 0

        for line_idx, line in enumerate(lines):
            line_len = len(line) + (1 if line_idx < len(lines) - 1 else 0)
            if line_idx > 0:
                line_stripped = line.strip()
                if line_stripped and NON_ARTICLE_BOUNDARY_PATTERN.match(line_stripped):
                    # Stop article text before this non-article structural delimiter
                    break
                body_lines.append(line)
            current_offset += line_len
            effective_block_len = current_offset

        char_end = match_start + len(text[match_start : match_start + effective_block_len].rstrip())
        if char_end < match_start:
            char_end = match_start

        art_text = "\n".join(body_lines).strip()
        if not art_text:
            art_text = heading or f"Madde {num}"

        articles.append(
            ParsedArticle(
                article_number=num,
                article_kind=kind_str,
                heading=heading,
                text=art_text,
                char_start=match_start,
                char_end=char_end,
                ordinal=idx,
            )
        )

    return ParsedLegislation(articles=articles)
