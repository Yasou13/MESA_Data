import hashlib
import re
import unicodedata


def _slugify(text: str) -> str:
    if not text:
        return ""
    tr_map = str.maketrans("ğüşöçığĞÜŞÖÇİI", "gusociigusoCII")
    text_tr = text.translate(tr_map)
    text_ascii = unicodedata.normalize("NFKD", text_tr).encode("ASCII", "ignore").decode("utf-8")
    cleaned = re.sub(r"[^\w\s-]", "", text_ascii.lower())
    return re.sub(r"[-\s]+", "-", cleaned).strip("-")


def build_legislation_id(legislation_type: str, number: str) -> str:
    safe_type = _slugify(legislation_type)
    safe_num = _slugify(number)
    return f"tr:legislation:{safe_type}:{safe_num}"


def build_legislation_version_id(document_id: str, snapshot_date: str, artifact_sha256: str) -> str:
    short_hash = artifact_sha256[:8]
    safe_date = snapshot_date.replace(" ", "")
    return f"{document_id}:version:{safe_date}:{short_hash}"


def normalize_article_number(value: str) -> str:
    return _slugify(value)


def build_article_id(legislation_id: str, article_number: str, article_kind: str) -> str:
    norm_num = normalize_article_number(article_number)
    if article_kind == "additional":
        prefix = "ek-"
    elif article_kind == "temporary":
        prefix = "gecici-"
    else:
        prefix = ""
    return f"{legislation_id}:article:{prefix}{norm_num}"


def build_decision_id(
    court: str,
    chamber: str | None,
    esas_no: str | None,
    karar_no: str | None,
    artifact_sha256: str,
) -> str:
    safe_court = _slugify(court) if court else "unknown"
    safe_chamber = _slugify(chamber) if chamber else "general"

    if esas_no and karar_no:
        clean_esas = esas_no.replace("/", "-").replace(" ", "")
        clean_karar = karar_no.replace("/", "-").replace(" ", "")
        return f"tr:case-law:{safe_court}:{safe_chamber}:{clean_esas}:{clean_karar}"
    else:
        return f"tr:case-law:{safe_court}:unknown:sha256-{artifact_sha256[:16]}"


def build_citation_id(source_record_id: str, start: int, end: int, target_id: str) -> str:
    raw = f"{source_record_id}:{start}:{end}:{target_id}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"citation:sha256:{digest}"
