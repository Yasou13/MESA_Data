import ipaddress
import socket
from collections.abc import Generator
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
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if is_ip_private(str(ip_obj)):
            raise SSRFError(f"Access to private/local IP {hostname} is forbidden")
    except ValueError:
        pass


def validate_url_host(url: str, require_https: bool = True):
    parsed = urlparse(url)

    if parsed.username or parsed.password:
        raise SourcePolicyError("URL userinfo (user@host) is not allowed")

    if require_https and parsed.scheme != "https":
        raise SSRFError(f"URL scheme must be HTTPS, got: {parsed.scheme}")

    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Invalid URL: missing hostname")

    hostname_norm = hostname.lower().rstrip(".")
    check_literal_ip_safety(hostname_norm)

    if parsed.port and parsed.port not in (80, 443):
        raise SSRFError(f"Non-standard port {parsed.port} is forbidden")

    try:
        addr_info = socket.getaddrinfo(hostname_norm, None)
        if not addr_info:
            raise URLFetchError(f"Could not resolve hostname {hostname}")
        for family, _, _, _, sockaddr in addr_info:
            ip_str = str(sockaddr[0])
            if is_ip_private(ip_str):
                raise SSRFError(f"Access to private/local IP {ip_str} ({hostname}) is forbidden")
    except socket.gaierror as e:
        raise URLFetchError(f"Could not resolve hostname {hostname}: {e}") from e


def validate_source_policy(
    source_id: str,
    url: str,
    document_family: str | None = None,
    sources_yaml_path: Path | None = None,
):
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

    if document_family and document_family not in source_info.families:
        raise SourcePolicyError(
            f"SOURCE_FAMILY_NOT_ALLOWED: Family '{document_family}' not allowed for source '{source_id}'. Allowed families: {source_info.families}"
        )

    parsed_url = urlparse(url)
    if not parsed_url.hostname:
        raise SourcePolicyError("Invalid URL: missing hostname")

    host_norm = parsed_url.hostname.lower().rstrip(".")
    parsed_base = urlparse(source_info.base_url)
    if not parsed_base.hostname:
        raise SourcePolicyError(f"Bozuk source base_url: {source_info.base_url}")

    base_host_norm = parsed_base.hostname.lower().rstrip(".")

    allowed_hosts = [base_host_norm]
    if hasattr(source_info, "allowed_redirect_hosts") and source_info.allowed_redirect_hosts:
        for h in source_info.allowed_redirect_hosts:
            allowed_hosts.append(h.lower().rstrip("."))

    is_allowed = False
    for ah in allowed_hosts:
        if host_norm == ah:
            is_allowed = True
            break
        if ah.startswith("www.") and host_norm == ah[4:]:
            is_allowed = True
            break
        if not ah.startswith("www.") and host_norm == f"www.{ah}":
            is_allowed = True
            break
        if host_norm.endswith("." + ah):
            is_allowed = True
            break

    if not is_allowed:
        raise SourcePolicyError(
            f"URL domain '{parsed_url.hostname}' does not match allowed source domain '{base_host_norm}'"
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
    url: str,
    source_id: str | None = None,
    document_family: str | None = None,
    max_bytes: int = 50 * 1024 * 1024,
    timeout_seconds: float = 30.0,
    require_https: bool = True,
    sources_yaml_path: Path | None = None,
) -> tuple[int, dict[str, str], Generator[bytes, None, None]]:
    """
    Safely fetches a URL with source policy checks, SSRF checks, timeout, and streaming size limits.
    Enforces follow_redirects=False and validates every redirect step.
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

            # Check literal IP safety first (e.g. 127.0.0.1) so SSRFError is raised immediately
            parsed_curr = urlparse(current_url)
            if parsed_curr.hostname:
                check_literal_ip_safety(parsed_curr.hostname.lower().rstrip("."))

            if source_id:
                validate_source_policy(source_id, current_url, document_family, sources_yaml_path)

            validate_url_host(current_url, require_https=require_https)

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
