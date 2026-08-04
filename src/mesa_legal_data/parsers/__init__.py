from .text_normalizer import normalize_text
from .pdf import parse_pdf, OCRRequiredError, PDFParseError
from .html import parse_html, HTMLParseError
from .legislation import parse_legislation_text, ParsedArticle, ParsedLegislation
from .decision import parse_decision_text, ParsedDecision
from .citations import extract_citations, Citation

__all__ = [
    "normalize_text",
    "parse_pdf",
    "OCRRequiredError",
    "PDFParseError",
    "parse_html",
    "HTMLParseError",
    "parse_legislation_text",
    "ParsedArticle",
    "ParsedLegislation",
    "parse_decision_text",
    "ParsedDecision",
    "extract_citations",
    "Citation",
]
