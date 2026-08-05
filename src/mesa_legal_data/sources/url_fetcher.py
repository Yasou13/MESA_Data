import ipaddress
import socket
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from mesa_legal_data.config import load_sources


class URLFetchError(Exception):
    pass


class SSRFError(URLFetchError):
    pass


class SizeLimitExceededError(URLFetchError):
    pass


class SourcePolicyError(URLFetchError):
    pass


@dataclass(frozen=True)
class ValidatedSourcePolicy:
    source_id: str
    document_family: str
    base_host: str
    allowed_hosts: frozenset[str]
    allowed_redirect_hosts: frozenset[str]
    timeout_seconds: float
    retries: int
    max_download_bytes: int
    user_agent: str
    min_interval_seconds: float


def is_ip_private(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return True


def check_literal_ip_safety(hostname: str):
    norm = hostname.lower().rstrip(".")
    if norm in ("localhost", "localhost.localdomain"):
        raise SSRFError(f"Access to private/local host {hostname} is forbidden")
    try:
        ip_obj = ipaddress.ip_address(norm)
        if is_ip_private(str(ip_obj)):
            raise SSRFError(f"Access to private/local IP {hostname} is forbidden")
    except ValueError:
        pass


def validate_url_host(url: str):
    """
    Validates pre-request DNS resolution and IP safety for non-literal domain names.
    Production path strictly rejects non-HTTPS schemes.
    """
    parsed = urlparse(url)

    if parsed.username or parsed.password:
        raise SourcePolicyError("URL userinfo (user@host) is not allowed")

    if parsed.scheme != "https":
        raise SSRFError(f"URL scheme must be HTTPS, got: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Invalid URL: missing hostname")

    try:
        norm_ascii = hostname.lower().rstrip(".").encode("idna").decode("ascii")
    except Exception as e:
        raise SourcePolicyError(f"Invalid IDNA hostname '{hostname}': {e}") from e

    check_literal_ip_safety(norm_ascii)

    if parsed.port and parsed.port not in (80, 443):
        raise SSRFError(f"Non-standard port {parsed.port} is forbidden")

    try:
        addr_info = socket.getaddrinfo(norm_ascii, None)
        if not addr_info:
            raise URLFetchError(f"Could not resolve hostname {hostname}")
        for family, _, _, _, sockaddr in addr_info:
            ip_str = str(sockaddr[0])
            if is_ip_private(ip_str):
                raise SSRFError(f"Access to private/local IP {ip_str} ({hostname}) is forbidden")
    except socket.gaierror as e:
        raise URLFetchError(f"Could not resolve hostname {hostname}: {e}") from e


def validate_source_request(
    *,
    source_id: str,
    document_family: str,
    url: str,
    is_redirect: bool = False,
    sources_yaml_path: Path | None = None,
) -> ValidatedSourcePolicy:
    """
    Central source policy validator.
    Strictly checks source existence, enabled status, family permission, access_mode,
    HTTPS scheme, and explicit host allowlist (NO IMPLICIT SUBDOMAINS).
    """
    if not source_id or not isinstance(source_id, str) or not source_id.strip():
        raise SourcePolicyError("SOURCE_REQUIRED: source_id is required and cannot be empty")

    if not document_family or not isinstance(document_family, str) or not document_family.strip():
        raise SourcePolicyError("SOURCE_FAMILY_REQUIRED: document_family is required and cannot be empty")

    if sources_yaml_path is None:
        sources_yaml_path = Path(__file__).parent.parent.parent.parent / "config" / "sources.yaml"

    if not sources_yaml_path.exists():
        raise SourcePolicyError(f"Sources config file not found at {sources_yaml_path}")

    sources_cfg = load_sources(sources_yaml_path)
    if source_id not in sources_cfg.sources:
        raise SourcePolicyError(f"SOURCE_NOT_FOUND: Source ID '{source_id}' not found in sources.yaml")

    source_info = sources_cfg.sources[source_id]
    if not source_info.enabled:
        raise SourcePolicyError(f"SOURCE_DISABLED: Source '{source_id}' is disabled in configuration")

    if document_family not in source_info.families:
        raise SourcePolicyError(
            f"SOURCE_FAMILY_NOT_ALLOWED: Family '{document_family}' not allowed for source '{source_id}'. Allowed families: {source_info.families}"
        )

    if hasattr(source_info, "access_mode") and source_info.access_mode not in (
        "manual",
        "approved_web",
        "licensed_api",
    ):
        raise SourcePolicyError(f"SOURCE_ACCESS_MODE_NOT_ALLOWED: Access mode '{source_info.access_mode}' not allowed")

    if hasattr(source_info, "http") and hasattr(source_info.http, "user_agent"):
        ua = source_info.http.user_agent.lower()
        if "operator_contact" in ua or "contact-email" in ua or "placeholder" in ua:
            if hasattr(source_info, "access_mode") and source_info.access_mode != "manual":
                raise SourcePolicyError(f"USER_AGENT_INVALID: User-Agent '{source_info.http.user_agent}' contains unconfigured contact placeholder")

    parsed_url = urlparse(url)
    if parsed_url.scheme != "https":
        raise SSRFError(f"URL scheme must be HTTPS, got: {parsed_url.scheme}")

    if not parsed_url.hostname:
        raise SourcePolicyError("Invalid URL: missing hostname")

    try:
        host_norm = parsed_url.hostname.lower().rstrip(".").encode("idna").decode("ascii")
    except Exception as e:
        raise SourcePolicyError(f"Invalid IDNA hostname '{parsed_url.hostname}': {e}") from e

    parsed_base = urlparse(source_info.base_url)
    if not parsed_base.hostname:
        raise SourcePolicyError(f"Bozuk source base_url: {source_info.base_url}")

    try:
        base_host_norm = parsed_base.hostname.lower().rstrip(".").encode("idna").decode("ascii")
    except Exception as e:
        raise SourcePolicyError(f"Invalid base_url IDNA hostname '{parsed_base.hostname}': {e}") from e

    # Build EXPLICIT host allowlist (NO implicit wildcard/subdomain matching, NO auto www prefixing)
    allowed_hosts_set: set[str] = {base_host_norm}

    if hasattr(source_info, "allowed_hosts") and source_info.allowed_hosts:
        for h in source_info.allowed_hosts:
            h_norm = h.lower().rstrip(".").encode("idna").decode("ascii")
            allowed_hosts_set.add(h_norm)

    allowed_redirect_set: set[str] = set()
    if hasattr(source_info, "allowed_redirect_hosts") and source_info.allowed_redirect_hosts:
        for h in source_info.allowed_redirect_hosts:
            h_norm = h.lower().rstrip(".").encode("idna").decode("ascii")
            allowed_redirect_set.add(h_norm)

    if is_redirect:
        valid_set = allowed_hosts_set | allowed_redirect_set
    else:
        valid_set = allowed_hosts_set

    if host_norm not in valid_set:
        raise SourcePolicyError(
            f"SOURCE_HOST_NOT_ALLOWED: URL domain '{parsed_url.hostname}' does not match allowed source domain '{base_host_norm}'"
        )

    return ValidatedSourcePolicy(
        source_id=source_id,
        document_family=document_family,
        base_host=base_host_norm,
        allowed_hosts=frozenset(allowed_hosts_set),
        allowed_redirect_hosts=frozenset(allowed_redirect_set),
        timeout_seconds=float(source_info.http.timeout_seconds),
        retries=int(source_info.http.retries),
        max_download_bytes=int(source_info.http.max_download_bytes),
        user_agent=str(source_info.http.user_agent),
        min_interval_seconds=float(source_info.http.min_interval_seconds),
    )


def validate_source_policy(
    source_id: str,
    url: str,
    document_family: str | None = None,
    sources_yaml_path: Path | None = None,
):
    """
    Backwards-compatible wrapper that delegates to validate_source_request.
    """
    family = document_family or "legislation"
    validate_source_request(
        source_id=source_id,
        document_family=family,
        url=url,
        is_redirect=False,
        sources_yaml_path=sources_yaml_path,
    )


def detect_html_error_page(body_text: str) -> str | None:
    low = body_text.lower()
    error_keywords = [
        ("captcha", "CAPTCHA challenge page detected"),
        ("güvenlik doğrulaması", "Security verification page detected"),
        ("access denied", "Access Denied page detected"),
        ("forbidden", "Forbidden page detected"),
        ("404 not found", "404 Not Found page detected"),
        ("500 internal server error", "500 Internal Server Error page detected"),
    ]
    for kw, msg in error_keywords:
        if kw in low:
            return msg
    return None


def fetch_url_stream(
    *,
    url: str,
    source_id: str,
    document_family: str,
    max_bytes: int = 50 * 1024 * 1024,
    timeout_seconds: float = 30.0,
    sources_yaml_path: Path | None = None,
) -> tuple[int, dict[str, str], Generator[bytes, None, None]]:
    """
    Safely fetches a URL with mandatory source policy checks, SSRF checks, timeout, and streaming size limits.
    Enforces follow_redirects=False and validates every redirect step against explicit source policy and IP safety.
    """
    current_url = url
    visited: set[str] = set()
    MAX_REDIRECTS = 3

    client = httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout_seconds),
        headers={
            "User-Agent": "MESA-Legal-Data/0.1 (+operator_contact)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.8",
        },
    )

    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            if current_url in visited:
                raise SSRFError(f"Redirect loop detected for URL: {current_url}")
            visited.add(current_url)

            # 1. Scheme check
            parsed_curr = urlparse(current_url)
            if parsed_curr.scheme != "https":
                raise SSRFError(f"URL scheme must be HTTPS, got: {parsed_curr.scheme}")

            # 2. Literal / Loopback IP check (SSRFError raised immediately without DNS)
            if parsed_curr.hostname:
                check_literal_ip_safety(parsed_curr.hostname.lower().rstrip("."))

            # 3. Source policy domain & permission check (SourcePolicyError raised before DNS for domain mismatch)
            is_red = redirect_count > 0
            validate_source_request(
                source_id=source_id,
                document_family=document_family,
                url=current_url,
                is_redirect=is_red,
                sources_yaml_path=sources_yaml_path,
            )

            # 4. Pre-request DNS resolution & IP safety check
            validate_url_host(current_url)

            req = client.build_request("GET", current_url)
            resp = client.send(req, stream=True)

            if resp.status_code in (301, 302, 303, 307, 308):
                if redirect_count >= MAX_REDIRECTS:
                    resp.close()
                    client.close()
                    raise URLFetchError(f"Too many redirects (max {MAX_REDIRECTS})")

                location = resp.headers.get("Location") or resp.headers.get("location")
                resp.close()
                if not location:
                    client.close()
                    raise URLFetchError("Redirect status received without Location header")

                current_url = urljoin(current_url, location)
                continue

            if resp.status_code != 200:
                resp.close()
                client.close()
                raise URLFetchError(f"HTTP status {resp.status_code}")

            def stream_generator():
                downloaded = 0
                try:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            raise SizeLimitExceededError(f"Download size exceeded max limit of {max_bytes} bytes")
                        yield chunk
                finally:
                    resp.close()
                    client.close()

            headers_dict = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status_code, headers_dict, stream_generator()

        client.close()
        raise URLFetchError("Too many redirects")
    except Exception:
        client.close()
        raise
