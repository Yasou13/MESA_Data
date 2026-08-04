from mesa_legal_data.parsers.citations import extract_citations


def test_extract_citations():
    text = """
    Türk Borçlar Kanunu'nun 117. maddesi uyarınca borçlunun temerrüdü...
    Ayrıca 4721 sayılı Kanun'un 1. maddesi uyarınca hakim takdir yetkisini kullanır.
    TMK m. 2 gereğince dürüstlük kuralı esastır.
    TCK 53 gereğince hak yoksunluğu uygulanır.
    """
    citations = extract_citations(text)
    assert len(citations) >= 4

    target_ids = [c.target_article_id for c in citations]
    assert "tr:legislation:law:6098:article:117" in target_ids
    assert "tr:legislation:law:4721:article:1" in target_ids
    assert "tr:legislation:law:4721:article:2" in target_ids
    assert "tr:legislation:law:5237:article:53" in target_ids
