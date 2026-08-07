import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from mesa_legal_data.harvest.models import DiscoveredDocument
from mesa_legal_data.harvest.normalization import build_canonical_key

SECTION_TYPE_MAP: dict[str, tuple[str, str]] = {
    "KANUNLAR": ("legislation", "law"),
    "CUMHURBAŞKANLIĞI KARARNAMELERİ": ("legislation", "presidential_decree"),
    "CUMHURBAŞKANI KARARLARI": ("legislation", "presidential_decision"),
    "YÖNETMELİKLER": ("legislation", "regulation"),
    "TEBLİĞLER": ("legislation", "communique"),
    "YARGI BÖLÜMÜ": ("decision", "court_decision"),
    "ANAYASA MAHKEMESİ KARARLARI": ("decision", "court_decision"),
    "YARGITAY KARARLARI": ("decision", "court_decision"),
    "DANIŞTAY KARARLARI": ("decision", "court_decision"),
}

EXCLUDED_SECTIONS = {
    "İLÂN BÖLÜMÜ",
    "ARTIRMA, EKSİLTME VE İHALE İLÂNLARI",
    "ÇEŞİTLİ İLÂNLAR",
    "İLAN BÖLÜMÜ",
}


class DiscoveryStructureChangedError(Exception):
    pass


class ResmiGazeteDiscoveryAdapter:
    name: str = "resmi_gazete"

    def __init__(self, http_client: httpx.Client | None = None):
        self._http_client = http_client
        self._current_cursor: dict[str, Any] = {}

    def parse_html_fihrist(self, html_content: str, pub_date: date, page_url: str) -> list[DiscoveredDocument]:
        soup = BeautifulSoup(html_content, "html.parser")
        discovered: list[DiscoveredDocument] = []

        # Check for structural baseline elements
        sections = soup.find_all(["div", "section", "table"], class_=re.compile(r"fihrist|bolum|section|content", re.I))
        if not sections and not soup.find_all("a"):
            raise DiscoveryStructureChangedError(f"Resmî Gazete page structure unexpected at {page_url}")

        current_section = "GENEL"
        doc_count = 0

        # Scan titles and links
        elements = soup.find_all(["h1", "h2", "h3", "h4", "div", "p", "a"])
        for el in elements:
            text_upper = el.get_text(strip=True).upper()

            # Section header detection
            for sec_key in SECTION_TYPE_MAP:
                if sec_key in text_upper:
                    current_section = sec_key
                    break

            for ex_key in EXCLUDED_SECTIONS:
                if ex_key in text_upper:
                    current_section = ex_key
                    break

            if current_section in EXCLUDED_SECTIONS:
                continue

            if el.name == "a" and el.get("href"):
                href = str(el["href"]).strip()
                if not href or href.startswith("javascript:") or href.startswith("#"):
                    continue

                full_url = urljoin(page_url, href)
                title = el.get_text(strip=True) or "Resmî Gazete Belgesi"

                if current_section in SECTION_TYPE_MAP:
                    family, doc_type = SECTION_TYPE_MAP[current_section]
                else:
                    family, doc_type = "legislation", "unknown"

                doc_count += 1
                doc_id_part = f"{pub_date.strftime('%Y%m%d')}-{doc_count}"
                canonical_key = build_canonical_key("resmi_gazete", family, doc_type, pub_date.isoformat(), doc_id_part)
                document_id = f"tr:{family}:{doc_type}:rg-{pub_date.strftime('%Y%m%d')}-{doc_count}"

                discovered.append(
                    DiscoveredDocument(
                        source_id="resmi_gazete",
                        canonical_key=canonical_key,
                        document_id=document_id,
                        family=family,
                        document_type=doc_type,
                        title=title,
                        publication_date=pub_date,
                        document_url=full_url,
                        discovery_page_url=page_url,
                        section=current_section,
                        priority=150 if doc_type in ("law", "presidential_decree") else 100,
                        selection_reasons=(f"resmi_gazete_section:{current_section}",),
                    )
                )

        return discovered

    def discover_date(self, target_date: date, page_html: str | None = None) -> list[DiscoveredDocument]:
        page_url = f"https://www.resmigazete.gov.tr/eskiler/{target_date.strftime('%Y/%m/%Y%m%d')}.htm"

        if page_html is None:
            if self._http_client is None:
                client = httpx.Client(timeout=10.0)
            else:
                client = self._http_client

            resp = client.get(page_url)
            if resp.status_code != 200:
                return []
            page_html = resp.text

        return self.parse_html_fihrist(page_html, target_date, page_url)
