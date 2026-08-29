from mesa_legal_data.parsers.citations import extract_citations


def test_extracted_never_automatically_validated():
    text = "5237 sayılı Türk Ceza Kanunu'nun 81. maddesi uyarınca ceza verilir."
    citations = extract_citations(text)
    assert len(citations) >= 1
    cit = citations[0]
    # Extraction must NEVER mark citation as validated or human_verified
    assert cit.citation_status != "HUMAN_VERIFIED"
    assert cit.citation_status in ("EXTRACTED", "RESOLVED")


def test_citation_coordinate_span_exact_slice():
    text = "İşbu karar 6100 sayılı Hukuk Muhakemeleri Kanunu madde 119 uyarınca verilmiştir."
    citations = extract_citations(text)
    assert len(citations) >= 1
    cit = citations[0]
    # Exact Unicode slice parity check
    assert text[cit.char_start : cit.char_end] == cit.raw_text


def test_expanded_turkish_numbered_laws():
    cases = [
        ("Bu hüküm 5237 sayılı Kanun gereğince uygulanır.", "5237"),
        ("657 sayılı Devlet Memurları Kanunu kapsamında görev yapmaktadır.", "657"),
        ("1 sayılı Cumhurbaşkanlığı Kararnamesi gereğince işlem yapıldı.", "1"),
        ("2577 sayılı İdari Yargılama Usulü Kanunu m. 7 uyarınca dava açılmıştır.", "2577"),
        ("6698 sayılı Kişisel Verilerin Korunması Kanunu madde 5/1 uyarınca.", "6698"),
    ]
    for text, expected_num in cases:
        citations = extract_citations(text)
        assert len(citations) >= 1, f"Failed to extract law citation from: {text}"
        found = any(expected_num in (c.target_legislation_id or "") or expected_num in c.raw_text for c in citations)
        assert found, f"Expected law number {expected_num} in citations for text: {text}"


def test_turkish_legal_code_aliases():
    cases = [
        ("TCK m. 81 uyarınca kasten öldürme suçu", "5237", "81"),
        ("CMK madde 100 gereğince tutuklama kararı verildi", "5271", "100"),
        ("HMK m. 119 gereğince dava dilekçesi eksikliği", "6100", "119"),
        ("TMK 166 maddesi uyarınca boşanma davası", "4721", "166"),
        ("TBK m. 49 uyarınca haksız fiil sorumluluğu", "6098", "49"),
        ("İİK m. 68 gereğince itirazın kaldırılması", "2004", "68"),
        ("İYUK 27/2 uyarınca yürütmenin durdurulması", "2577", "27"),
        ("AY m. 36 uyarınca adil yargılanma hakkı", "2709", "36"),
        ("KVKK m. 6 gereğince özel nitelikli kişisel veri", "6698", "6"),
        ("VUK m. 359 uyarınca vergi kaçakçılığı suçu", "213", "359"),
    ]
    for text, law_num, article in cases:
        citations = extract_citations(text)
        assert len(citations) >= 1, f"Failed to extract alias citation for: {text}"
        cit = citations[0]
        assert cit.target_legislation_id == f"tr:legislation:{'constitution' if law_num == '2709' else 'law'}:{law_num}"
        assert cit.target_article_id == f"{cit.target_legislation_id}:article:{article}"
        assert text[cit.char_start : cit.char_end] == cit.raw_text


def test_false_positive_prevention():
    # Random numbers, dates, times, or currencies without legal context must not be recognized as citations
    false_positives = [
        "Toplantı saat 1500 sularında başladı ve 1800'de bitti.",
        "Şirketin 2024 yılı toplam geliri 5000 TL olarak gerçekleşmiştir.",
        "Bu konuda yaklaşık 100 kişi görüş bildirmiştir.",
        "Dosyadaki 12345 adet evrak incelenmiştir.",
    ]
    for text in false_positives:
        citations = extract_citations(text)
        assert len(citations) == 0, f"False positive detected in: '{text}', citations: {citations}"


def test_lowercase_ay_and_random_4857_are_not_resolved():
    text = "Bu ay 4857 başvuru kaydedildi; ilgili Kanun hükmü ayrıca incelenecektir."
    citations = extract_citations(text)

    assert not any(c.target_legislation_id == "tr:legislation:constitution:2709" for c in citations)
    assert not any(c.target_legislation_id == "tr:legislation:law:4857" for c in citations)
    assert any(c.citation_status == "UNRESOLVED" for c in citations)


def test_unknown_numbered_law_stays_extracted_until_resolution():
    citations = extract_citations("9999 sayılı Kanun'un 3. maddesi uyarınca işlem yapıldı.")

    assert len(citations) == 1
    assert citations[0].target_legislation_id == "tr:legislation:law:9999"
    assert citations[0].target_article_id == "tr:legislation:law:9999:article:3"
    assert citations[0].citation_status == "EXTRACTED"


def test_temporal_relation_hints():
    cases = [
        ("Bu madde 5237 sayılı Kanun ile değiştirilmiştir.", "amends"),
        ("Söz konusu fıkra 6100 sayılı Kanun ile yürürlükten kaldırılmıştır.", "repeals"),
        ("Bu fıkra 2577 sayılı Kanun ile eklenmiştir.", "adds"),
        ("Bu kural 657 sayılı Kanun uyarınca uygulanır.", None),
    ]
    for text, expected_hint in cases:
        citations = extract_citations(text)
        assert len(citations) >= 1, f"Failed citation extraction in: {text}"
        cit = citations[0]
        assert cit.relation_hint == expected_hint, f"Expected {expected_hint} but got {cit.relation_hint} in: {text}"


def test_unresolved_citation_lifecycle():
    text = "İlgili Kanun hükümleri ve mevzuat uyarınca işlem yapılması gerekir."
    citations = extract_citations(text)
    for cit in citations:
        if cit.target_legislation_id is None:
            assert cit.citation_status == "UNRESOLVED"
