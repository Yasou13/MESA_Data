from mesa_legal_data.parsers.encoding import decode_source_bytes
from mesa_legal_data.parsers.html import parse_html


def test_parse_html_cp1254_turkish_characters():
    html = """<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=Windows-1254">
</head>
<body>
<p>Madde 9- Bu Tarife yayım tarihinde yürürlüğe girer.</p>
<p>Çalışma, işçi, işveren, değişiklik, tebliğ ve yönetmelik.</p>
</body>
</html>"""
    raw_bytes = html.encode("cp1254")

    parsed = parse_html(raw_bytes)

    assert "yayım" in parsed, f"Expected 'yayım' in parsed text, got: {parsed}"
    assert "yürürlüğe" in parsed, f"Expected 'yürürlüğe' in parsed text, got: {parsed}"
    assert "Çalışma" in parsed
    assert "işçi" in parsed
    assert "işveren" in parsed
    assert "değişiklik" in parsed
    assert "tebliğ" in parsed
    assert "yönetmelik" in parsed
    assert "yaym" not in parsed
    assert "yrrle" not in parsed


def test_decode_source_bytes_all_encodings():
    # 1. UTF-8
    utf8_str = "İş Sağlığı ve Güvenliği Yönetmeliği — ÇALIŞMA"
    raw_utf8 = utf8_str.encode("utf-8")
    text, enc = decode_source_bytes(raw_utf8, is_html=False)
    assert text == utf8_str
    assert enc == "utf-8"

    # 2. UTF-8 BOM
    raw_bom = b"\xef\xbb\xbf" + utf8_str.encode("utf-8")
    text, enc = decode_source_bytes(raw_bom, is_html=False)
    assert text == utf8_str
    assert enc == "utf-8-sig"

    # 3. Windows-1254 with HTML meta
    html_cp1254 = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=Windows-1254"></head><body>(1) Bu Tarife yayım tarihinde yürürlüğe girer.</body></html>"""
    raw_cp1254 = html_cp1254.encode("cp1254")
    text, enc = decode_source_bytes(raw_cp1254, is_html=True)
    assert "yayım" in text
    assert "yürürlüğe" in text
    assert enc == "windows-1254"

    # 4. ISO-8859-9 with HTML meta
    html_iso = """<html><head><meta charset="iso-8859-9"></head><body>(1) Bu Tarife yayım tarihinde yürürlüğe girer.</body></html>"""
    raw_iso = html_iso.encode("iso-8859-9")
    text, enc = decode_source_bytes(raw_iso, is_html=True)
    assert "yayım" in text
    assert "yürürlüğe" in text
    assert enc == "iso-8859-9"

    # 5. Raw cp1254 text without HTML meta
    plain_cp1254 = "Çalışma ve Sosyal Güvenlik Bakanlığı tebliği yayım tarihi".encode("cp1254")
    text, enc = decode_source_bytes(plain_cp1254, is_html=False)
    assert "Çalışma" in text
    assert "Güvenlik" in text
    assert "tebliği" in text
    assert "yayım" in text
