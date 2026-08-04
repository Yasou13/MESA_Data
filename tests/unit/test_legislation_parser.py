from mesa_legal_data.parsers.legislation import parse_legislation_text


def test_parse_legislation_text():
    sample_text = """
    TÜRK MEDENİ KANUNU
    
    MADDE 1 - Hukukun uygulanması ve kaynakları
    Kanun, sözüyle ve özüyle değindiği bütün konularda uygulanır.
    
    MADDE 2 - Dürüst davranma
    Herkes, haklarını kullanırken dürüstlük kurallarına uymak zorundadır.
    
    EK MADDE 1 - Ek Hüküm
    Bu kanuna eklenen maddeler saklıdır.
    
    GEÇİCİ MADDE 1 - Geçici Hüküm
    Bu kanunun yürürlüğe girdiği tarihteki davalar...
    """
    parsed = parse_legislation_text(sample_text)
    assert len(parsed.articles) == 4

    # Madde 1
    m1 = parsed.articles[0]
    assert m1.article_number == "1"
    assert m1.article_kind == "standard"
    assert m1.heading == "Hukukun uygulanması ve kaynakları"
    assert "sözüyle ve özüyle değindiği" in m1.text

    # Madde 2
    m2 = parsed.articles[1]
    assert m2.article_number == "2"
    assert m2.heading == "Dürüst davranma"

    # Ek Madde 1
    ek1 = parsed.articles[2]
    assert ek1.article_number == "1"
    assert ek1.article_kind == "additional"
    assert ek1.heading == "Ek Hüküm"

    # Geçici Madde 1
    g1 = parsed.articles[3]
    assert g1.article_number == "1"
    assert g1.article_kind == "temporary"
    assert g1.heading == "Geçici Hüküm"
