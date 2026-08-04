import re
import unicodedata
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

LAW_ALIASES = {
    "TURK MEDENI KANUNU": ("4721", "law"),
    "MEDENI KANUN": ("4721", "law"),
    "TMK": ("4721", "law"),
    "TURK BORCLAR KANUNU": ("6098", "law"),
    "BORCLAR KANUNU": ("6098", "law"),
    "TBK": ("6098", "law"),
    "TURK CEZA KANUNU": ("5237", "law"),
    "TCK": ("5237", "law"),
    "CEZA MUHAKEMESI KANUNU": ("5271", "law"),
    "CMK": ("5271", "law"),
    "HUKUK MUHAKEMELERI KANUNU": ("6100", "law"),
    "HMK": ("6100", "law"),
    "ICRA VE IFLAS KANUNU": ("2004", "law"),
    "IIK": ("2004", "law"),
    "IS KANUNU": ("4857", "law"),
    "TURK TICARET KANUNU": ("6102", "law"),
    "TTK": ("6102", "law"),
    "ANAYASA": ("2709", "constitution"),
}


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_text: str
    target_legislation_id: str
    target_article_id: Optional[str] = None


def _to_ascii_upper(s: str) -> str:
    tr_map = str.maketrans("ğüşöçığĞÜŞÖÇİI", "gusociigusoCII")
    s_tr = s.translate(tr_map)
    return unicodedata.normalize("NFKD", s_tr).encode("ASCII", "ignore").decode("utf-8").upper()


def extract_citations(text: str) -> List[Citation]:
    if not text:
        return []

    citations: List[Citation] = []
    ascii_text = _to_ascii_upper(text)

    # 1. Matching law numbers (e.g. 4721 sayılı Kanun'un 1. maddesi)
    num_pattern = re.compile(
        r"\b(?P<law_num>4721|6098|5237|5271|6100|2004|4857|6102|2709)\b(?:\s*(?:SAYILI|S\.)?\s*(?:KANUN|K\.)?\s*(?:'[A-Z]+)?)?\s*(?:MADDESI|MADDE|M\.)?\s*\.?\s*(?P<art_num>\d+)?",
        re.IGNORECASE,
    )

    for match in num_pattern.finditer(ascii_text):
        law_num = match.group("law_num")
        art_num = match.group("art_num")
        leg_type = "constitution" if law_num == "2709" else "law"
        leg_id = f"tr:legislation:{leg_type}:{law_num}"
        art_id = f"{leg_id}:article:{art_num}" if art_num else None

        start, end = match.span()
        citations.append(
            Citation(
                raw_text=text[start:end],
                target_legislation_id=leg_id,
                target_article_id=art_id,
            )
        )

    # 2. Matching alias-based citations (e.g. Türk Borçlar Kanunu'nun 117. maddesi, TMK m. 2)
    alias_pattern = re.compile(
        r"\b(?P<alias>TURK MEDENI KANUNU|MEDENI KANUN|TMK|TURK BORCLAR KANUNU|BORCLAR KANUNU|TBK|TURK CEZA KANUNU|TCK|CEZA MUHAKEMESI KANUNU|CMK|HUKUK MUHAKEMELERI KANUNU|HMK|ICRA VE IFLAS KANUNU|IIK|IS KANUNU|TURK TICARET KANUNU|TTK|ANAYASA)\b(?:\s*'[A-Z]+)?\s*(?:MADDESI|MADDE|M\.)?\s*\.?\s*(?P<art_num>\d+)?",
        re.IGNORECASE,
    )

    for match in alias_pattern.finditer(ascii_text):
        alias_key = match.group("alias").upper()
        if alias_key in LAW_ALIASES:
            law_num, leg_type = LAW_ALIASES[alias_key]
            art_num = match.group("art_num")
            leg_id = f"tr:legislation:{leg_type}:{law_num}"
            art_id = f"{leg_id}:article:{art_num}" if art_num else None

            start, end = match.span()
            raw = text[start:end]

            cit = Citation(
                raw_text=raw,
                target_legislation_id=leg_id,
                target_article_id=art_id,
            )

            if cit not in citations:
                citations.append(cit)

    return citations
