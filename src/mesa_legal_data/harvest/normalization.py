import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "ref",
    "source",
}


def normalize_url(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Handle IDNA for host
    if "@" in netloc:
        userinfo, hostport = netloc.split("@", 1)
    else:
        userinfo, hostport = "", netloc

    if ":" in hostport:
        host, port = hostport.split(":", 1)
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            hostport = host
    else:
        host = hostport

    try:
        host = host.encode("idna").decode("ascii")
    except Exception:
        pass

    if ":" in hostport:
        port_part = ":" + hostport.split(":", 1)[1]
        netloc = (userinfo + "@" if userinfo else "") + host + port_part
    else:
        netloc = (userinfo + "@" if userinfo else "") + host

    # Normalize path
    path = parsed.path
    if not path:
        path = "/"
    path = re.sub(r"//+", "/", path)

    # Sort & clean query params
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered_params = []
    for k in sorted(query_params.keys()):
        if k.lower() in TRACKING_PARAMS:
            continue
        vals = sorted(query_params[k])
        for v in vals:
            filtered_params.append((k, v))

    clean_query = urlencode(filtered_params)

    # Strip fragment
    return urlunparse((scheme, netloc, path, parsed.params, clean_query, ""))


def build_canonical_key(
    source_id: str,
    family: str,
    document_type: str,
    pub_date: str | None,
    doc_identifier: str,
) -> str:
    clean_source = source_id.strip().lower()
    clean_type = document_type.strip().lower()
    clean_id = re.sub(r"[^\w\.-]", "_", doc_identifier.strip()).lower()
    if pub_date:
        return f"{clean_source}:{pub_date}:{clean_type}:{clean_id}"
    return f"{clean_source}:{clean_type}:{clean_id}"
