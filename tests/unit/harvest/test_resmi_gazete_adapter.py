from datetime import date

import pytest

from mesa_legal_data.harvest.discovery.resmi_gazete import (
    DiscoveryStructureChangedError,
    ResmiGazeteDiscoveryAdapter,
)

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
