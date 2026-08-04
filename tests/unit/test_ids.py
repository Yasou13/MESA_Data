from mesa_legal_data.ids import (
    build_article_id,
    build_citation_id,
    build_decision_id,
    build_legislation_id,
    build_legislation_version_id,
)


def test_ids_generation():
    leg_id = build_legislation_id("law", "4721")
    assert leg_id == "tr:legislation:law:4721"

    ver_id = build_legislation_version_id(leg_id, "2026-08-05", "8f15c921abc")
    assert ver_id == "tr:legislation:law:4721:version:2026-08-05:8f15c921"

    art_id = build_article_id(leg_id, "1", "standard")
    assert art_id == "tr:legislation:law:4721:article:1"

    ek_art_id = build_article_id(leg_id, "2", "additional")
    assert ek_art_id == "tr:legislation:law:4721:article:ek-2"

    dec_id = build_decision_id("YARGITAY", "3. Hukuk Dairesi", "2023/4125", "2024/1872", "sha256")
    assert dec_id == "tr:case-law:yargitay:3-hukuk-dairesi:2023-4125:2024-1872"

    cit_id = build_citation_id(dec_id, 10, 20, leg_id)
    assert cit_id.startswith("citation:sha256:")
