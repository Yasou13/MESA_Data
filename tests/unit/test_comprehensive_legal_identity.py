import pytest

from mesa_legal_data.parsers.citations import extract_citations
from mesa_legal_data.parsers.legislation import parse_legislation_text
from mesa_legal_data.publisher.chunker import plan_source_chunks


def test_article_parser_preserves_extended_turkish_article_identity() -> None:
    parsed = parse_legislation_text(
        "\n".join(
            [
                "MADDE 1- Olağan hüküm.",
                "EK MADDE 1- Ek hüküm.",
                "GEÇİCİ MADDE 1- Geçici hüküm.",
                "MÜKERRER MADDE 1- Mükerrer hüküm.",
                "MADDE 1/A- Harf ekli hüküm.",
            ]
        )
    )

    assert [(article.article_kind, article.article_number) for article in parsed.articles] == [
        ("standard", "1"),
        ("additional", "1"),
        ("temporary", "1"),
        ("repeated", "1"),
        ("standard", "1/A"),
    ]


def test_chunk_plan_is_lossless_and_rejects_overlapping_article_identity() -> None:
    canonical = "KANUN BAŞLIĞI\nMADDE 1- Bir.\nBİRİNCİ BÖLÜM\nMADDE 2- İki."
    first_start = canonical.index("MADDE 1")
    gap_start = canonical.index("BİRİNCİ BÖLÜM")
    second_start = canonical.index("MADDE 2")
    records = [
        {
            "record_id": "law:article:1",
            "record_type": "article",
            "article_number": "1",
            "article_kind": "standard",
            "char_start": first_start,
            "char_end": gap_start,
            "ordinal": 1,
        },
        {
            "record_id": "law:article:2",
            "record_type": "article",
            "article_number": "2",
            "article_kind": "standard",
            "char_start": second_start,
            "char_end": len(canonical),
            "ordinal": 2,
        },
    ]

    chunks = plan_source_chunks(
        document_id="tr:legislation:law:6098",
        version_id="tr:legislation:law:6098:version:2026-01-01:a",
        canonical_text=canonical,
        records=records,
    )
    assert "".join(chunk.content for chunk in chunks) == canonical
    assert any(chunk.chunk_type == "general" and "BİRİNCİ BÖLÜM" in chunk.content for chunk in chunks)

    overlapping = [dict(records[0]), dict(records[1], char_start=gap_start - 2)]
    with pytest.raises(ValueError, match="overlap"):
        plan_source_chunks(
            document_id="tr:legislation:law:6098",
            version_id="tr:legislation:law:6098:version:2026-01-01:a",
            canonical_text=canonical,
            records=overlapping,
        )


def test_chunk_plan_carries_structured_law_article_and_temporal_identity() -> None:
    canonical = "MADDE 1/A- Hüküm."
    chunks = plan_source_chunks(
        document_id="tr:legislation:law:6098",
        version_id="tr:legislation:law:6098:version:2026-01-01:a",
        canonical_text=canonical,
        records=[
            {
                "record_id": "tr:legislation:law:6098:article:1-a",
                "record_type": "article",
                "article_number": "1/A",
                "article_kind": "standard",
                "char_start": 0,
                "char_end": len(canonical),
                "ordinal": 1,
                "law_number": "6098",
                "law_title": "TÜRK BORÇLAR KANUNU",
                "effective_from": "2026-01-01",
                "effective_to": None,
            }
        ],
    )

    assert chunks[0].metadata == {
        "article_id": "tr:legislation:law:6098:article:1-a",
        "article_number": "1/A",
        "article_kind": "standard",
        "law_number": "6098",
        "law_title": "TÜRK BORÇLAR KANUNU",
        "effective_from": "2026-01-01",
        "effective_to": None,
        "piece_index": 1,
        "total_pieces": 1,
    }


def test_chunk_coordinate_recovery_does_not_mutate_canonical_records() -> None:
    records = [{"record_id": "a1", "record_type": "article", "article_number": "1", "content": "MADDE 1- A."}]
    plan_source_chunks(document_id="law", version_id="law:v1", canonical_text="MADDE 1- A.", records=records)
    assert "char_start" not in records[0]
    assert "char_end" not in records[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("6098 sayılı Kanunun 1/A maddesi değiştirilmiştir.", "tr:legislation:law:6098:article:1-a"),
        ("TBK geçici madde 2 uyarınca", "tr:legislation:law:6098:article:gecici-2"),
        ("TCK mükerrer madde 5 uyarınca", "tr:legislation:law:5237:article:mukerrer-5"),
    ],
)
def test_citation_article_identity_preserves_suffix_and_kind(source: str, expected: str) -> None:
    assert extract_citations(source)[0].target_article_id == expected


def test_syntactic_citation_candidate_is_not_falsely_resolved() -> None:
    citation = extract_citations("6098 sayılı Kanunun 1 inci maddesi değiştirilmiştir.")[0]

    assert citation.target_legislation_id == "tr:legislation:law:6098"
    assert citation.target_article_id == "tr:legislation:law:6098:article:1"
    assert citation.citation_status == "EXTRACTED"
    assert citation.relation_hint == "amends"
