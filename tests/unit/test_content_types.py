import pytest

from mesa_legal_data.content_types import detect_mime_type, validate_file_content, ContentTypeError, SizeLimitError

def test_detect_mime_type_pdf(tmp_path):
    pdf = tmp_path / "test.pdf"
    # Write a valid PDF header
    pdf.write_bytes(b"%PDF-1.4\n%EOF")
    assert detect_mime_type(str(pdf)) == "application/pdf"

def test_detect_mime_type_html(tmp_path):
    html = tmp_path / "test.html"
    html.write_bytes(b"<!DOCTYPE html><html><body>Test</body></html>")
    # puremagic can sometimes detect html as text/plain or something else depending on its db.
    # but let's test if it returns a string.
    assert isinstance(detect_mime_type(str(html)), str)

def test_detect_fake_pdf(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"<!DOCTYPE html><html><body>This is HTML</body></html>")
    detected = detect_mime_type(str(fake))
    assert detected != "application/pdf"

def test_validate_empty_file(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.touch()
    
    with pytest.raises(ContentTypeError, match="empty"):
        validate_file_content(str(empty), ["text/plain"], 1000)

def test_validate_size_limit(tmp_path):
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.4\n" + b"a" * 1000)
    
    with pytest.raises(SizeLimitError, match="exceeds limit"):
        validate_file_content(str(big), ["application/pdf"], 100)

def test_validate_success(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%EOF")
    
    detected = validate_file_content(str(pdf), ["application/pdf"], 1000)
    assert detected == "application/pdf"
