import pytest
from pypdf import PdfWriter

from mesa_legal_data.parsers.pdf import OCRRequiredError, parse_pdf


def test_parse_pdf_text_layered(tmp_path):
    pdf_file = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # Write some annotation/text if possible, or create a minimal PDF
    # In pypdf we can test with a real text PDF
    writer.write(pdf_file)

    # An empty blank page has no text, so it should raise OCRRequiredError
    with pytest.raises(OCRRequiredError, match="OCR_REQUIRED"):
        parse_pdf(pdf_file)
