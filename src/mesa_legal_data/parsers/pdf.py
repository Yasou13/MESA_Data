from pathlib import Path
from pypdf import PdfReader

from mesa_legal_data.parsers.text_normalizer import normalize_text


class PDFParseError(Exception):
    pass


class OCRRequiredError(PDFParseError):
    """
    Raised when a PDF contains no extractable text (image-only / requires OCR).
    """
    pass


def parse_pdf(pdf_path: Path) -> str:
    """
    Extracts text from a text-layered PDF using pypdf.
    Raises OCRRequiredError if no text can be extracted across all pages.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        raise PDFParseError(f"Failed to open PDF: {e}") from e

    extracted_pages = []
    total_text_length = 0

    for page_num, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
            normalized = normalize_text(page_text)
            if normalized:
                total_text_length += len(normalized)
                extracted_pages.append(normalized)
        except Exception as e:
            raise PDFParseError(f"Error reading page {page_num}: {e}") from e

    if total_text_length == 0:
        raise OCRRequiredError(f"PDF {pdf_path.name} contains no text layer (OCR_REQUIRED)")

    return "\n\n".join(extracted_pages)
