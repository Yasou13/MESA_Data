from mesa_legal_data.parsers.coverage import compute_parsing_coverage
from mesa_legal_data.parsers.legislation import parse_legislation_text
from mesa_legal_data.parsers.text_normalizer import normalize_text


def test_canonical_normalization_determinism():
    raw_1 = "TÜRK CEZA KANUNU\r\n\r\nMADDE 1 \u00a0-\u200b Ceza Kanununun amacı;\u0000"
    raw_2 = "TÜRK CEZA KANUNU\n\nMADDE 1  - Ceza Kanununun amacı;"

    canon_1 = normalize_text(raw_1)
    canon_2 = normalize_text(raw_2)

    assert canon_1 == canon_2
    assert "TÜRK CEZA KANUNU" in canon_1
    assert "MADDE 1 -" in canon_1
    assert "\u00a0" not in canon_1
    assert "\u200b" not in canon_1
    assert "\x00" not in canon_1


def test_article_source_spans_exact_slice_match():
    canonical_text = """TÜRK BORÇLAR KANUNU
Genel Hükümler

MADDE 1 - Sözleşme, tarafların iradelerini karşılıklı ve birbirine uygun olarak açıklamalarıyla kurulur.
İrade açıklaması, açık veya örtülü olabilir.

MADDE 2 - Taraflar sözleşmenin esaslı noktalarında uyuşmuşlarsa, ikinci derecedeki noktalar üzerinde durulmamış olsa bile, sözleşme kurulmuş sayılır.

EK MADDE 1 - Ek hüküm metni burada yer alır.

GEÇİCİ MADDE 1 - Geçici uygulama hükümleri."""

    parsed = parse_legislation_text(canonical_text, auto_normalize=False)

    assert len(parsed.articles) == 4

    # 1. Madde 1
    art1 = parsed.articles[0]
    assert art1.article_number == "1"
    assert art1.ordinal == 1
    assert art1.char_start is not None and art1.char_end is not None
    slice_1 = canonical_text[art1.char_start : art1.char_end]
    assert slice_1.startswith("MADDE 1 -")
    assert "İrade açıklaması, açık veya örtülü olabilir." in slice_1

    # 2. Madde 2
    art2 = parsed.articles[1]
    assert art2.article_number == "2"
    assert art2.ordinal == 2
    slice_2 = canonical_text[art2.char_start : art2.char_end]
    assert slice_2.startswith("MADDE 2 -")
    assert "sözleşme kurulmuş sayılır." in slice_2

    # 3. Ek Madde 1
    art_ek = parsed.articles[2]
    assert art_ek.article_number == "1"
    assert art_ek.article_kind == "additional"
    slice_ek = canonical_text[art_ek.char_start : art_ek.char_end]
    assert slice_ek.startswith("EK MADDE 1 -")

    # 4. Geçici Madde 1
    art_gec = parsed.articles[3]
    assert art_gec.article_number == "1"
    assert art_gec.article_kind == "temporary"
    slice_gec = canonical_text[art_gec.char_start : art_gec.char_end]
    assert slice_gec.startswith("GEÇİCİ MADDE 1 -")

    # Invariant: Spans do not overlap and are monotonically increasing
    assert (
        art1.char_start
        < art1.char_end
        <= art2.char_start
        < art2.char_end
        <= art_ek.char_start
        < art_ek.char_end
        <= art_gec.char_start
        < art_gec.char_end
    )


def test_parsing_coverage_with_preamble_and_annex():
    preamble = "TÜRK TİCARET KANUNU\nBaşlangıç Hükümleri ve Gerekçe\n\n"
    article_1 = "MADDE 1 - Türk Ticaret Kanunu genel esasları düzenler.\n\n"
    gap_heading = "İKİNCİ KISIM: Şirketler Hukuku\n\n"
    article_2 = "MADDE 2 - Ticari işler ticari hükümlere tabidir.\n\n"
    annex = "EK CETVEL: Yürürlük ve İntikal Hükümleri ile İlgili Tablolar."

    full_text = preamble + article_1 + gap_heading + article_2 + annex

    parsed = parse_legislation_text(full_text, auto_normalize=False)
    assert len(parsed.articles) == 2

    spans = [(a.char_start, a.char_end) for a in parsed.articles if a.char_start is not None and a.char_end is not None]
    coverage = compute_parsing_coverage(full_text, spans)

    assert coverage.canonical_chars == len(full_text)
    assert coverage.covered_chars > 0
    assert coverage.uncovered_chars > 0
    assert 0.0 < coverage.coverage_ratio < 1.0

    # Uncovered ranges classification
    uncovered = coverage.uncovered_ranges
    assert len(uncovered) == 3

    # Preamble range
    preamble_range = uncovered[0]
    assert preamble_range["candidate_type"] == "preamble"
    assert preamble_range["start"] == 0
    assert preamble_range["end"] == parsed.articles[0].char_start
    assert "TÜRK TİCARET KANUNU" in preamble_range["preview"]

    # Gap range
    gap_range = uncovered[1]
    assert gap_range["candidate_type"] == "gap"
    assert gap_range["start"] == parsed.articles[0].char_end
    assert gap_range["end"] == parsed.articles[1].char_start
    assert "İKİNCİ KISIM" in gap_range["preview"]

    # Annex / trailing range
    annex_range = uncovered[2]
    assert annex_range["candidate_type"] == "annex_trailing"
    assert annex_range["start"] == parsed.articles[1].char_end
    assert annex_range["end"] == len(full_text)
    assert "EK CETVEL" in annex_range["preview"]
