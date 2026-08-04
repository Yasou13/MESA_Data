from mesa_legal_data.parsers.text_normalizer import normalize_text

def test_normalize_text_turkish_preservation():
    input_text = "TÜRK MİLLİ EĞİTİM KANUNU - ŞÇÖĞÜIışçöğü"
    assert normalize_text(input_text) == input_text

def test_normalize_text_control_chars_and_spaces():
    input_text = "MADDE 1 \u00a0-\u200b Kanunun\tamacı.\u0000"
    expected = "MADDE 1 - Kanunun amacı."
    assert normalize_text(input_text) == expected

def test_normalize_text_multiline():
    input_text = "  Line 1   \r\n   Line 2  \n\n Line 3  "
    expected = "Line 1\nLine 2\n\nLine 3"
    assert normalize_text(input_text) == expected
