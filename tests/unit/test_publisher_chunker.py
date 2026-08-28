from mesa_legal_data.publisher.chunker import _split_oversized_text, plan_source_chunks


def test_chunker_structure_preservation_preamble_articles_annex():
    canonical_text = (
        "TÜRK CEZA KANUNU\n\nGenel Hükümler ve Başlangıç\n\n"
        "MADDE 1- Bu Kanunun amacı kişi hak ve özgürlüklerini korumaktır.\n\n"
        "MADDE 2- Kanunun açıkça suç saymadığı bir fiil için kimseye ceza verilemez.\n\n"
        "GEÇİCİ MADDE 1- Bu Kanunun yürürlüğe girmesinden önceki fiiller hakkında..."
    )

    p_end = canonical_text.index("MADDE 1")
    m1_start = p_end
    m1_end = canonical_text.index("MADDE 2")
    m2_start = m1_end
    m2_end = canonical_text.index("GEÇİCİ MADDE 1")
    annex_start = m2_end

    records = [
        {
            "record_id": "art-1",
            "record_type": "article",
            "article_number": "1",
            "title": "Madde 1",
            "char_start": m1_start,
            "char_end": m1_end,
            "ordinal": 1,
        },
        {
            "record_id": "art-2",
            "record_type": "article",
            "article_number": "2",
            "title": "Madde 2",
            "char_start": m2_start,
            "char_end": m2_end,
            "ordinal": 2,
        },
    ]

    chunks = plan_source_chunks(
        document_id="tr:legislation:law:5237",
        version_id="tr:legislation:law:5237:v1",
        canonical_text=canonical_text,
        records=records,
        content_limit_chars=500,
    )

    # Must produce 4 chunks: preamble, art 1, art 2, annex
    assert len(chunks) == 4
    assert chunks[0].chunk_type == "preamble"
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == m1_start

    assert chunks[1].chunk_type == "article"
    assert chunks[1].char_start == m1_start
    assert chunks[1].char_end == m1_end
    assert chunks[1].metadata.get("article_number") == "1"

    assert chunks[2].chunk_type == "article"
    assert chunks[2].char_start == m2_start
    assert chunks[2].char_end == m2_end

    assert chunks[3].chunk_type == "annex"
    assert chunks[3].char_start == annex_start
    assert chunks[3].char_end == len(canonical_text)


def test_chunker_oversized_split_on_paragraphs():
    long_paragraph_1 = "A" * 200
    long_paragraph_2 = "B" * 200
    text = f"{long_paragraph_1}\n\n{long_paragraph_2}"

    splits = _split_oversized_text(text, base_char_start=0, max_chars=250)
    assert len(splits) == 2
    assert splits[0][2] == f"{long_paragraph_1}\n\n"
    assert splits[1][2] == long_paragraph_2
    assert splits[0][0] == 0
    assert splits[0][1] == len(long_paragraph_1) + 2
    assert splits[1][0] == len(long_paragraph_1) + 2
    assert splits[1][1] == len(text)


def test_chunker_deterministic_invariants():
    canonical_text = "MADDE 1- Deneme içerik.\n\nMADDE 2- İkinci deneme içerik."
    records = [
        {
            "record_id": "art-1",
            "record_type": "article",
            "article_number": "1",
            "char_start": 0,
            "char_end": 24,
            "ordinal": 1,
        },
        {
            "record_id": "art-2",
            "record_type": "article",
            "article_number": "2",
            "char_start": 26,
            "char_end": len(canonical_text),
            "ordinal": 2,
        },
    ]

    run1 = plan_source_chunks(
        document_id="doc-1",
        version_id="doc-1:v1",
        canonical_text=canonical_text,
        records=records,
    )
    run2 = plan_source_chunks(
        document_id="doc-1",
        version_id="doc-1:v1",
        canonical_text=canonical_text,
        records=records,
    )

    assert len(run1) == len(run2)
    for c1, c2 in zip(run1, run2):
        assert c1.chunk_id == c2.chunk_id
        assert c1.content_hash == c2.content_hash
        assert c1.content == c2.content
        assert c1.char_start == c2.char_start
        assert c1.char_end == c2.char_end
