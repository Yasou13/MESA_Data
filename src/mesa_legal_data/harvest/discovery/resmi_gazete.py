import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from mesa_legal_data.harvest.models import DiscoveredDocument
from mesa_legal_data.harvest.normalization import build_canonical_key
from mesa_legal_data.parsers.text_normalizer import normalize_text
from mesa_legal_data.sources.url_fetcher import fetch_discovery_html

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

HEADER_SECTION_MAP: dict[str, str] = {
    "KANUNLAR": "KANUNLAR",
    "KANUN": "KANUNLAR",
    "CUMHURBAŞKANLIĞI KARARNAMELERİ": "CUMHURBAŞKANLIĞI KARARNAMELERİ",
    "CUMHURBAŞKANLIĞI KARARNAMESİ": "CUMHURBAŞKANLIĞI KARARNAMELERİ",
    "CUMHURBAŞKANI KARARLARI": "CUMHURBAŞKANI KARARLARI",
    "CUMHURBAŞKANI KARARI": "CUMHURBAŞKANI KARARLARI",
    "YÖNETMELİKLER": "YÖNETMELİKLER",
    "YÖNETMELİK": "YÖNETMELİKLER",
    "TEBLİĞLER": "TEBLİĞLER",
    "TEBLİĞ": "TEBLİĞLER",
    "YARGI BÖLÜMÜ": "YARGI BÖLÜMÜ",
    "ANAYASA MAHKEMESİ KARARLARI": "ANAYASA MAHKEMESİ KARARLARI",
    "ANAYASA MAHKEMESİ KARARI": "ANAYASA MAHKEMESİ KARARLARI",
    "YARGITAY KARARLARI": "YARGITAY KARARLARI",
    "YARGITAY KARARI": "YARGITAY KARARLARI",
    "DANIŞTAY KARARLARI": "DANIŞTAY KARARLARI",
    "DANIŞTAY KARARI": "DANIŞTAY KARARLARI",
}

EXCLUDED_SECTIONS = {
    "İLÂN BÖLÜMÜ",
    "ARTIRMA, EKSİLTME VE İHALE İLÂNLARI",
    "ÇEŞİTLİ İLÂNLAR",
    "İLAN BÖLÜMÜ",
}

ALL_EXCLUDED_HEADERS: set[str] = {
    "İLÂN BÖLÜMÜ",
    "İLAN BÖLÜMÜ",
    "ARTIRMA, EKSİLTME VE İHALE İLÂNLARI",
    "ARTIRMA, EKSİLTME VE İHALE İLÂNI",
    "ARTIRMA, EKSİLTME VE İHALE İLANLARI",
    "ARTIRMA, EKSİLTME VE İHALE İLANI",
    "ÇEŞİTLİ İLÂNLAR",
    "ÇEŞİTLİ İLÂN",
    "ÇEŞİTLİ İLANLAR",
    "ÇEŞİTLİ İLAN",
    "İLÂNLAR",
    "İLANLAR",
    "İLÂN",
    "İLAN",
    "YARGI İLÂNLARI",
    "YARGI İLÂNI",
    "YARGI İLANLARI",
    "YARGI İLANI",
}

OTHER_SECTION_HEADERS: set[str] = {
    "TBMM KARARI",
    "TBMM KARARLARI",
    "KURUL KARARI",
    "KURUL KARARLARI",
    "ATAMA KARARI",
    "ATAMA KARARLARI",
    "GENELGE",
    "GENELGELER",
}

NON_DOCUMENT_STEMS = {
    "index",
    "default",
    "main",
    "home",
    "anasayfa",
    "search",
    "arama",
    "contact",
    "iletisim",
    "about",
    "hakkimizda",
    "arsiv",
}

NON_DOCUMENT_EXTENSIONS = {
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
}


class DiscoveryStructureChangedError(Exception):
    pass


def is_resmi_gazete_document_link(url: str, pub_date: date) -> bool:
    if not url:
        return False
    parsed = urlparse(url)

    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return False

    if parsed.netloc and "resmigazete.gov.tr" not in parsed.netloc.lower():
        return False

    path_obj = Path(parsed.path)
    ext = path_obj.suffix.lower()

    if ext in NON_DOCUMENT_EXTENSIONS:
        return False

    stem = path_obj.stem.lower()
    if not stem or stem in NON_DOCUMENT_STEMS:
        return False

    date_prefix = pub_date.strftime("%Y%m%d")
    if stem.startswith(date_prefix) or re.search(r"\d{6,8}", stem):
        return True

    if ext in (".htm", ".html", ".pdf"):
        return True

    return False


class ResmiGazeteDiscoveryAdapter:
    name: str = "resmi_gazete"

    def __init__(self, http_client: httpx.Client | None = None):
        self._http_client = http_client
        self._current_cursor: dict[str, Any] = {}

    def parse_html_fihrist(self, html_content: str, pub_date: date, page_url: str) -> list[DiscoveredDocument]:
        soup = BeautifulSoup(html_content, "html.parser")
        discovered: list[DiscoveredDocument] = []

        current_section = "GENEL"

        elements = soup.find_all(["h1", "h2", "h3", "h4", "div", "p", "a"])
        for el in elements:
            text_norm = re.sub(r"\s+", " ", el.get_text() or "").strip()
            text_upper = text_norm.upper()

            # Section header detection: exact match only
            if el.name != "a":
                if text_upper in HEADER_SECTION_MAP:
                    current_section = HEADER_SECTION_MAP[text_upper]
                elif text_upper in ALL_EXCLUDED_HEADERS:
                    current_section = text_upper
                elif text_upper in OTHER_SECTION_HEADERS:
                    current_section = text_upper

            if (
                current_section in EXCLUDED_SECTIONS
                or current_section in ALL_EXCLUDED_HEADERS
                or "İLAN" in current_section
                or "İLÂN" in current_section
            ):
                continue

            if el.name == "a" and el.get("href"):
                href = str(el["href"]).strip()
                if not href or href.startswith("javascript:") or href.startswith("#"):
                    continue

                full_url = urljoin(page_url, href)
                if "ilanlar" in full_url.lower():
                    continue

                if not is_resmi_gazete_document_link(full_url, pub_date):
                    continue

                raw_title = el.get_text() or ""
                cleaned_title = normalize_text(raw_title)
                title = " ".join(line.strip() for line in cleaned_title.splitlines() if line.strip())
                title = re.sub(r"^[\s\u2010-\u2015\u2212\-–—]+", "", title).strip()
                if not title:
                    title = "Resmî Gazete Belgesi"

                if current_section in SECTION_TYPE_MAP:
                    family, doc_type = SECTION_TYPE_MAP[current_section]
                else:
                    family, doc_type = "legislation", "unknown"

                link_stem = Path(urlparse(full_url).path).stem
                if not link_stem or link_stem.lower() in NON_DOCUMENT_STEMS:
                    continue

                doc_id_part = link_stem
                canonical_key = build_canonical_key("resmi_gazete", family, doc_type, pub_date.isoformat(), doc_id_part)

                num_id: str | None = None
                if doc_type == "law":
                    m_law = re.search(r"^\s*(\d{3,5})\b", title)
                    if m_law:
                        num_id = m_law.group(1)
                elif doc_type == "presidential_decree":
                    m_decree = re.search(r"Kararname\s+Numaras[ıi]\s*:\s*(\d+)", title, re.IGNORECASE)
                    if not m_decree:
                        m_decree = re.search(
                            r"\b(\d+)\s+Say[ıi]l[ıi]\s+Cumhurba[şs]kanl[ıi][ğg][ıi]\s+Kararnamesi",
                            title,
                            re.IGNORECASE,
                        )
                    if m_decree:
                        num_id = m_decree.group(1)
                elif doc_type == "presidential_decision":
                    m_dec = re.search(r"Karar\s+Say[ıi]s[ıi]\s*:\s*(\d+)", title, re.IGNORECASE)
                    if m_dec:
                        num_id = m_dec.group(1)

                if num_id:
                    document_id = f"tr:{family}:{doc_type}:{num_id}"
                else:
                    document_id = f"tr:{family}:{doc_type}:rg-{doc_id_part}"

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

        if not discovered:
            text_plain = soup.get_text() if html_content else ""
            is_no_issue_day = (
                "yayımlanmamıştır" in text_plain.lower()
                or "mükerrer sayı yapılmamıştır" in text_plain.lower()
                or "resmî gazete yayımlanmamıştır" in text_plain.lower()
            )
            if not is_no_issue_day:
                raise DiscoveryStructureChangedError(
                    f"Resmî Gazete page structure unexpected or malformed at {page_url}"
                )

        return discovered

    def discover_date(
        self,
        target_date: date,
        page_html: str | None = None,
        sources_yaml_path: Path | None = None,
    ) -> list[DiscoveredDocument]:
        page_url = f"https://www.resmigazete.gov.tr/eskiler/{target_date.strftime('%Y/%m/%Y%m%d')}.htm"

        if page_html is None:
            if self._http_client is not None:
                resp = self._http_client.get(page_url)
                if resp.status_code == 404:
                    return []
                if resp.status_code != 200:
                    raise RuntimeError(f"Resmî Gazete HTTP discovery failed with status code {resp.status_code}")
                page_html = resp.text
            else:
                try:
                    page_html = fetch_discovery_html(
                        source_id="resmi_gazete",
                        family="legislation",
                        url=page_url,
                        sources_yaml_path=sources_yaml_path,
                    )
                except Exception as e:
                    if "404" in str(e):
                        return []
                    raise

        return self.parse_html_fihrist(page_html, target_date, page_url)
