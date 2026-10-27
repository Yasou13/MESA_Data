import re
from datetime import date
from pathlib import Path

import pytest

from mesa_legal_data.harvest.discovery.resmi_gazete import (
    DiscoveryStructureChangedError,
    ResmiGazeteDiscoveryAdapter,
)
from mesa_legal_data.parsers.encoding import decode_source_bytes

SAMPLE_RESMI_GAZETE_HTML = """
<!DOCTYPE html>
<html>
<head><title>07 Ağustos 2026 Tarihli ve 33000 Sayılı Resmî Gazete</title></head>
<body>
<div class="fihrist">
  <h2>KANUNLAR</h2>
  <a href="20260807-1.htm">7500 Sayılı İklim Değişikliği Kanunu</a>

  <h2>CUMHURBAŞKANLIĞI KARARNAMELERİ</h2>
  <a href="20260807-2.htm">150 Sayılı Cumhurbaşkanlığı Kararnamesi</a>

  <h2>YÖNETMELİKLER</h2>
  <a href="20260807-3.htm">Çevre Denetimi Yönetmeliği</a>

  <h2>İLÂN BÖLÜMÜ</h2>
  <a href="20260807-4.htm">İhale İlanı</a>
</div>
</body>
</html>
"""


def test_resmi_gazete_adapter_parsing():
    adapter = ResmiGazeteDiscoveryAdapter()
    pub_date = date(2026, 8, 7)
    docs = adapter.discover_date(pub_date, page_html=SAMPLE_RESMI_GAZETE_HTML)

    assert len(docs) == 3

    # KANUNLAR
    doc_law = docs[0]
    assert doc_law.family == "legislation"
    assert doc_law.document_type == "law"
    assert doc_law.title == "7500 Sayılı İklim Değişikliği Kanunu"
    assert doc_law.document_url == "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-1.htm"

    # CUMHURBAŞKANLIĞI KARARNAMELERİ
    doc_dec = docs[1]
    assert doc_dec.document_type == "presidential_decree"

    # YÖNETMELİKLER
    doc_reg = docs[2]
    assert doc_reg.document_type == "regulation"

    # İLÂN BÖLÜMÜ excluded
    assert not any(d.section == "İLÂN BÖLÜMÜ" for d in docs)


def test_resmi_gazete_adapter_structure_changed():
    adapter = ResmiGazeteDiscoveryAdapter()
    pub_date = date(2026, 8, 7)
    with pytest.raises(DiscoveryStructureChangedError):
        adapter.parse_html_fihrist("", pub_date, "https://www.resmigazete.gov.tr/empty")


def test_golden_resmi_gazete_20260812():
    golden_path = Path(__file__).resolve().parents[2] / "golden" / "resmi_gazete" / "20260812.htm"
    html_content, _ = decode_source_bytes(golden_path.read_bytes(), is_html=True)
    adapter = ResmiGazeteDiscoveryAdapter()
    pub_date = date(2026, 8, 12)
    docs = adapter.parse_html_fihrist(
        html_content, pub_date, "https://www.resmigazete.gov.tr/eskiler/2026/08/20260812.htm"
    )

    # 1. Regulation link 20260812-2.htm -> type regulation
    reg_docs = [d for d in docs if "20260812-2.htm" in d.document_url]
    assert len(reg_docs) == 1
    reg_doc = reg_docs[0]
    assert reg_doc.document_type == "regulation"
    assert reg_doc.family == "legislation"
    assert "Binaların Yıkılması" in reg_doc.title

    # 2. Every title has no \r, \n, \xa0, control chars, or leading dashes
    for d in docs:
        assert "\r" not in d.title
        assert "\n" not in d.title
        assert "\xa0" not in d.title
        assert not re.search(r"[\x00-\x1f\x7f-\x9f]", d.title)
        assert not d.title.startswith("–")
        assert not d.title.startswith("-")

    # 3. No link in an İLAN / İLÂN section is returned
    for d in docs:
        assert "İLAN" not in d.section.upper()
        assert "İLÂN" not in d.section.upper()
        assert "ilanlar" not in d.document_url


def test_golden_resmi_gazete_20260813():
    golden_path = Path(__file__).resolve().parents[2] / "golden" / "resmi_gazete" / "20260813.htm"
    html_content, _ = decode_source_bytes(golden_path.read_bytes(), is_html=True)
    adapter = ResmiGazeteDiscoveryAdapter()
    pub_date = date(2026, 8, 13)
    docs = adapter.parse_html_fihrist(
        html_content, pub_date, "https://www.resmigazete.gov.tr/eskiler/2026/08/20260813.htm"
    )

    # Decision link 20260813-0.pdf -> type presidential_decision, document_id tr:legislation:presidential_decision:11606
    dec_docs = [d for d in docs if "20260813-0.pdf" in d.document_url]
    assert len(dec_docs) == 1
    dec_doc = dec_docs[0]
    assert dec_doc.document_type == "presidential_decision"
    assert dec_doc.document_id == "tr:legislation:presidential_decision:11606"
    assert "Özel Tüketim Vergisi" in dec_doc.title

    for d in docs:
        assert "\r" not in d.title
        assert "\n" not in d.title
        assert "\xa0" not in d.title
        assert not re.search(r"[\x00-\x1f\x7f-\x9f]", d.title)
        assert not d.title.startswith("–")
        assert not d.title.startswith("-")
        assert "İLAN" not in d.section.upper()
        assert "İLÂN" not in d.section.upper()


def test_golden_resmi_gazete_20260809_laws_and_decrees():
    golden_path = Path(__file__).resolve().parents[2] / "golden" / "resmi_gazete" / "20260809.htm"
    html_content, _ = decode_source_bytes(golden_path.read_bytes(), is_html=True)
    adapter = ResmiGazeteDiscoveryAdapter()
    pub_date = date(2026, 8, 9)
    docs = adapter.parse_html_fihrist(
        html_content, pub_date, "https://www.resmigazete.gov.tr/eskiler/2026/08/20260809.htm"
    )

    # Law links -> type law, document_id tr:legislation:law:<number>, title keeps its number
    law7592 = [d for d in docs if "20260809-2.htm" in d.document_url]
    assert len(law7592) == 1
    assert law7592[0].document_type == "law"
    assert law7592[0].document_id == "tr:legislation:law:7592"
    assert law7592[0].title.startswith("7592")
    assert "Yükseköğretim Kanunu" in law7592[0].title

    # Presidential decree -> kararname number
    decree199 = [d for d in docs if "20260809-3.pdf" in d.document_url]
    assert len(decree199) == 1
    assert decree199[0].document_type == "presidential_decree"
    assert decree199[0].document_id == "tr:legislation:presidential_decree:199"

    # Presidential decision -> Karar Sayısı
    decision11577 = [d for d in docs if "20260809-13.pdf" in d.document_url]
    assert len(decision11577) == 1
    assert decision11577[0].document_type == "presidential_decision"
    assert decision11577[0].document_id == "tr:legislation:presidential_decision:11577"

    for d in docs:
        assert "\r" not in d.title
        assert "\n" not in d.title
        assert "\xa0" not in d.title
        assert not re.search(r"[\x00-\x1f\x7f-\x9f]", d.title)
        assert "İLAN" not in d.section.upper()
        assert "İLÂN" not in d.section.upper()
