from mesa_legal_data.parsers.decision import parse_decision_text


def test_parse_decision_text():
    sample = """
    YARGITAY 3. HUKUK DAİRESİ
    Esas No : 2023/4125
    Karar No : 2024/1872
    Karar Tarihi : 15.03.2024
    
    TARAFLARIN İDDİA VE SAVUNMALARI...
    GEREKÇE:
    Türk Borçlar Kanununun 117. maddesi uyarınca...
    """
    parsed = parse_decision_text(sample)
    assert parsed.court == "YARGITAY"
    assert "3. HUKUK DAİRESİ" in parsed.chamber
    assert parsed.esas_no == "2023/4125"
    assert parsed.karar_no == "2024/1872"
    assert parsed.decision_date == "2024-03-15"
    assert "GEREKÇE" in parsed.text
