from datetime import date

import pytest

from mesa_legal_data.harvest.discovery.resmi_gazete import (
    DiscoveryStructureChangedError,
    ResmiGazeteDiscoveryAdapter,
    is_resmi_gazete_document_link,
)


def test_deterministic_document_id_and_canonical_key_on_html_shuffle() -> None:
    adapter = ResmiGazeteDiscoveryAdapter()
    pub_date = date(2026, 8, 7)
    page_url = "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807.htm"

    html_order_1 = """
    <html><body>
    <div>YÖNETMELİKLER</div>
    <a href="20260807-1.htm">Yönetmelik A</a>
    <a href="20260807-2.htm">Yönetmelik B</a>
    </body></html>
    """

    html_order_2 = """
    <html><body>
    <div>YÖNETMELİKLER</div>
    <a href="20260807-2.htm">Yönetmelik B</a>
    <a href="20260807-1.htm">Yönetmelik A</a>
    </body></html>
    """

    docs1 = adapter.parse_html_fihrist(html_order_1, pub_date, page_url)
    docs2 = adapter.parse_html_fihrist(html_order_2, pub_date, page_url)

    assert len(docs1) == 2
    assert len(docs2) == 2

    # Map by link stem
    by_stem1 = {d.document_url: (d.document_id, d.canonical_key) for d in docs1}
    by_stem2 = {d.document_url: (d.document_id, d.canonical_key) for d in docs2}

    url1 = "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-1.htm"
    url2 = "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-2.htm"

    assert by_stem1[url1] == by_stem2[url1]
    assert by_stem1[url2] == by_stem2[url2]

    assert by_stem1[url1][0] == "tr:legislation:regulation:rg-20260807-1"
    assert by_stem1[url2][0] == "tr:legislation:regulation:rg-20260807-2"


def test_is_resmi_gazete_document_link_filtering() -> None:
    pub_date = date(2026, 8, 7)

    assert is_resmi_gazete_document_link("https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-1.htm", pub_date)
    assert is_resmi_gazete_document_link("https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-1.pdf", pub_date)

    # Rejections
    assert not is_resmi_gazete_document_link("https://www.resmigazete.gov.tr/index.htm", pub_date)
    assert not is_resmi_gazete_document_link("https://www.resmigazete.gov.tr/anasayfa", pub_date)
    assert not is_resmi_gazete_document_link("javascript:void(0)", pub_date)
    assert not is_resmi_gazete_document_link("https://www.resmigazete.gov.tr/style.css", pub_date)
    assert not is_resmi_gazete_document_link("https://external-domain.com/doc.pdf", pub_date)


def test_structure_changed_fail_closed() -> None:
    adapter = ResmiGazeteDiscoveryAdapter()
    pub_date = date(2026, 8, 7)
    page_url = "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807.htm"

    malformed_html = "<html><body><div>Bilinmeyen Sayfa Yapisi</div><p>Belge yok</p></body></html>"

    with pytest.raises(DiscoveryStructureChangedError):
        adapter.parse_html_fihrist(malformed_html, pub_date, page_url)
