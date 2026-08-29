import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

CitationStatus = Literal["EXTRACTED", "RESOLVED", "UNRESOLVED", "HUMAN_VERIFIED"]
RelationHint = Literal["amends", "repeals", "adds"]

# Legal Code Definitions: (Canonical Name, Alias, Law Number, Doc Family/Type)
LEGAL_CODES = [
    ("TÜRK BORÇLAR KANUNU", "TBK", "6098", "law"),
    ("TURK BORCLAR KANUNU", "TBK", "6098", "law"),
    ("BORÇLAR KANUNU", "BK", "6098", "law"),
    ("BORCLAR KANUNU", "BK", "6098", "law"),
    ("TÜRK CEZA KANUNU", "TCK", "5237", "law"),
    ("TURK CEZA KANUNU", "TCK", "5237", "law"),
    ("CEZA MUHAKEMESİ KANUNU", "CMK", "5271", "law"),
    ("CEZA MUHAKEMESI KANUNU", "CMK", "5271", "law"),
    ("CEZA MUHAKEMELERİ USULÜ KANUNU", "CMUK", "1412", "law"),
    ("HUKUK MUHAKEMELERİ KANUNU", "HMK", "6100", "law"),
    ("HUKUK MUHAKEMELERI KANUNU", "HMK", "6100", "law"),
    ("HUKUK USULÜ MUHAKEMELERİ KANUNU", "HUMK", "1086", "law"),
    ("TÜRK MEDENİ KANUNU", "TMK", "4721", "law"),
    ("TURK MEDENI KANUNU", "TMK", "4721", "law"),
    ("MEDENİ KANUN", "MK", "4721", "law"),
    ("MEDENI KANUN", "MK", "4721", "law"),
    ("TÜRK TİCARET KANUNU", "TTK", "6102", "law"),
    ("TURK TICARET KANUNU", "TTK", "6102", "law"),
    ("TİCARET KANUNU", "TK", "6102", "law"),
    ("İCRA VE İFLAS KANUNU", "İİK", "2004", "law"),
    ("ICRA VE IFLAS KANUNU", "IIK", "2004", "law"),
    ("İŞ KANUNU", "İŞK", "4857", "law"),
    ("IS KANUNU", "ISK", "4857", "law"),
    ("İDARİ YARGILAMA USULÜ KANUNU", "İYUK", "2577", "law"),
    ("IDARI YARGILAMA USULU KANUNU", "IYUK", "2577", "law"),
    ("VERGİ USUL KANUNU", "VUK", "213", "law"),
    ("VERGI USUL KANUNU", "VUK", "213", "law"),
    ("KİŞİSEL VERİLERİN KORUNMASI KANUNU", "KVKK", "6698", "law"),
    ("KISISEL VERILERIN KORUNMASI KANUNU", "KVK", "6698", "law"),
    ("AVUKATLIK KANUNU", "AVK", "1136", "law"),
    ("POLİS VAZİFE VE SALÂHİYET KANUNU", "PVSK", "2559", "law"),
    ("POLIS VAZIFE VE SALAHIYET KANUNU", "PVSK", "2559", "law"),
    ("TÜRKİYE CUMHURİYETİ ANAYASASI", "AY", "2709", "constitution"),
    ("TURKIYE CUMHURIYETI ANAYASASI", "AY", "2709", "constitution"),
    ("ANAYASA", None, "2709", "constitution"),
]

# Build lookup map for aliases and canonical names
ALIAS_MAP: dict[str, tuple[str, str]] = {}
for name, alias, num, kind in LEGAL_CODES:
    ALIAS_MAP[name.upper()] = (num, kind)
    if alias:
        ALIAS_MAP[alias.upper()] = (num, kind)

KNOWN_LEGISLATION_NUMBERS = {num for _, _, num, _ in LEGAL_CODES}


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_text: str
    target_legislation_id: str | None = None
    target_article_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    citation_status: CitationStatus = "EXTRACTED"
    relation_hint: RelationHint | None = None


# Pattern 1: Numbered Law Citations with explicit context
# e.g. "4857 sayılı Kanun'un 1. maddesi", "6698 sayılı Kişisel Verilerin Korunması Kanunu m. 9", "7500 sayılı Kanun 3. maddesi"
NUMBERED_LAW_PATTERN = re.compile(
    r"\b(?P<law_num>[1-9]\d{0,4})\s+sayılı\s+(?:[A-Za-zÇĞİÖŞÜçğıöşü\s]{0,50}?)(?:Kanun(?:u|un|una|unda|undan|a|da|dan|lar|ları)?|KHK(?:'nin|'ye|'de)?|Cumhurbaşkanlığı\s+Kararnamesi(?:'nin)?|Yasa(?:sı|nın)?)\b(?:\s*['’][A-Za-zçğıöşüÇĞİÖŞÜ]+)?(?:\s+(?:(?:(?:ek|geçici)\s+)?(?:madde|maddesi|m\.)\s*\.?\s*(?P<art_num_m>\d+|[A-ZÇĞİÖŞÜ]+)|(?P<art_num_num>\d+)(?:\.|\s*['’]?(?:nci|üncü|inci|ıncı|uncu))?\s*(?:maddesi|madde)|(?P<art_num_bare>\d+)\b))?",
    re.IGNORECASE,
)

# Pattern 2: Named Law / Code Alias Citations
# e.g. "Türk Borçlar Kanunu'nun 117. maddesi", "TMK m. 2", "TCK 53", "HMK 119", "İş Kanunu 25/II"
ALIAS_NAMES = sorted(ALIAS_MAP.keys(), key=lambda x: len(x), reverse=True)
ALIAS_PATTERN_STR = "|".join(re.escape(k) for k in ALIAS_NAMES)

ALIAS_LAW_PATTERN = re.compile(
    rf"\b(?P<alias>{ALIAS_PATTERN_STR})\b(?:\s*['’][A-Za-zçğıöşüÇĞİÖŞÜ]+)?(?:\s+(?:(?:(?:ek|geçici)\s+)?(?:madde|maddesi|m\.)\s*\.?\s*(?P<art_num_m>\d+|[A-ZÇĞİÖŞÜ]+)|(?P<art_num_num>\d+)(?:\.|\s*['’]?(?:nci|üncü|inci|ıncı|uncu))?\s*(?:maddesi|madde)|(?P<art_num_bare>\d+)\b))?",
    re.IGNORECASE,
)

# Pattern 3: Unresolved candidates (generic references without specific number/code)
UNRESOLVED_CANDIDATE_PATTERN = re.compile(
    r"\b(?:ilgili|anılan|mezkûr|söz\s+konusu)\s+(?:Kanun(?:u|un|a|da)?|maddesi|hükmü)\b",
    re.IGNORECASE,
)

# Temporal relation patterns (Deterministic legal modification verbs)
AMENDS_PATTERN = re.compile(
    r"(?:değiştirilmiştir|değişiklik\s+yapılmıştır|değişen\s+şekliyle|şeklinde\s+değiştirilmiş)",
    re.IGNORECASE,
)
REPEALS_PATTERN = re.compile(
    r"(?:yürürlükten\s+kaldırılmıştır|mülga\s+kılınmıştır|mülga\s+edilmiştir|iptal\s+edilmiştir|\bmülga\b)",
    re.IGNORECASE,
)
ADDS_PATTERN = re.compile(
    r"(?:eklenmiştir|ihdas\s+edilmiştir|ilave\s+edilmiştir)",
    re.IGNORECASE,
)


def _detect_relation_hint(context_window: str) -> RelationHint | None:
    if AMENDS_PATTERN.search(context_window):
        return "amends"
    if REPEALS_PATTERN.search(context_window):
        return "repeals"
    if ADDS_PATTERN.search(context_window):
        return "adds"
    return None


def extract_citations(text: str) -> list[Citation]:
    """
    Extracts deterministic legal citations and references with exact canonical coordinate spans.
    Enforces the citation lifecycle:
      - RESOLVED: Target document / article reliably mapped.
      - UNRESOLVED: Citation candidate found but target ambiguous/unspecified.
      - EXTRACTED: Raw candidate state before resolution.
    """
    if not text:
        return []

    citations: list[Citation] = []
    seen_spans: set[tuple[int, int]] = set()

    # 1. Numbered Law Citations
    for match in NUMBERED_LAW_PATTERN.finditer(text):
        start, end = match.span()
        raw = text[start:end]
        law_num = match.group("law_num")
        art_num = match.group("art_num_m") or match.group("art_num_num") or match.group("art_num_bare")

        leg_type = "constitution" if law_num == "2709" else "law"
        leg_id = f"tr:legislation:{leg_type}:{law_num}"
        art_id = f"{leg_id}:article:{art_num}" if art_num else None

        window_start = max(0, start - 50)
        window_end = min(len(text), end + 100)
        relation = _detect_relation_hint(text[window_start:window_end])

        citations.append(
            Citation(
                raw_text=raw,
                target_legislation_id=leg_id,
                target_article_id=art_id,
                char_start=start,
                char_end=end,
                # A syntactically valid number is only a resolution candidate
                # unless it belongs to the deterministic legislation registry.
                citation_status=(
                    "RESOLVED" if law_num in KNOWN_LEGISLATION_NUMBERS else "EXTRACTED"
                ),
                relation_hint=relation,
            )
        )
        seen_spans.add((start, end))

    # 2. Alias-based Code Citations
    for match in ALIAS_LAW_PATTERN.finditer(text):
        start, end = match.span()
        if any(s <= start < e or s < end <= e for s, e in seen_spans):
            continue

        raw = text[start:end]
        alias_key = match.group("alias").strip().upper()
        raw_alias = match.group("alias").strip()
        if len(raw_alias) <= 3 and raw_alias != raw_alias.upper():
            # Avoid resolving ordinary Turkish words such as "ay" as the AY alias.
            continue
        law_tuple = ALIAS_MAP.get(alias_key)
        if not law_tuple:
            continue

        law_num, leg_type = law_tuple
        art_num = match.group("art_num_m") or match.group("art_num_num") or match.group("art_num_bare")
        leg_id = f"tr:legislation:{leg_type}:{law_num}"
        art_id = f"{leg_id}:article:{art_num}" if art_num else None

        window_start = max(0, start - 50)
        window_end = min(len(text), end + 100)
        relation = _detect_relation_hint(text[window_start:window_end])

        citations.append(
            Citation(
                raw_text=raw,
                target_legislation_id=leg_id,
                target_article_id=art_id,
                char_start=start,
                char_end=end,
                citation_status="RESOLVED",
                relation_hint=relation,
            )
        )
        seen_spans.add((start, end))

    # 3. Unresolved Candidates
    for match in UNRESOLVED_CANDIDATE_PATTERN.finditer(text):
        start, end = match.span()
        if any(s <= start < e or s < end <= e for s, e in seen_spans):
            continue

        raw = text[start:end]
        citations.append(
            Citation(
                raw_text=raw,
                target_legislation_id=None,
                target_article_id=None,
                char_start=start,
                char_end=end,
                citation_status="UNRESOLVED",
                relation_hint=None,
            )
        )
        seen_spans.add((start, end))

    citations.sort(key=lambda c: (c.char_start or 0, c.char_end or 0))
    return citations
