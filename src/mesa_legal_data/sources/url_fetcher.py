import ipaddress
import socket
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse

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


def validate_url_host(url: str, require_https: bool = True):
    parsed = urlparse(url)
    if require_https and parsed.scheme != "https":
        raise SSRFError(f"URL scheme must be HTTPS, got: {parsed.scheme}")

    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Invalid URL: missing hostname")

    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = str(sockaddr[0])
            if is_ip_private(ip_str):
                raise SSRFError(f"Access to private/local IP {ip_str} ({hostname}) is forbidden")
    except socket.gaierror as e:
        raise URLFetchError(f"Could not resolve hostname {hostname}: {e}") from e


def validate_source_policy(source_id: str, url: str, sources_yaml_path: Path | None = None):
    if sources_yaml_path is None:
        sources_yaml_path = Path(__file__).parent.parent.parent.parent / "config" / "sources.yaml"

    if not sources_yaml_path.exists():
        return

    sources_cfg = load_sources(sources_yaml_path)
    if source_id not in sources_cfg.sources:
        raise SourcePolicyError(f"Source ID '{source_id}' not found in sources.yaml")

    source_info = sources_cfg.sources[source_id]
    if not source_info.enabled:
        raise SourcePolicyError(f"Source '{source_id}' is disabled in configuration")

    parsed_url = urlparse(url)
    parsed_base = urlparse(source_info.base_url)

    if (
        parsed_url.hostname
        and parsed_base.hostname
        and not (
            parsed_url.hostname == parsed_base.hostname or parsed_url.hostname.endswith("." + parsed_base.hostname)
        )
    ):
        raise SourcePolicyError(
            f"URL domain '{parsed_url.hostname}' does not match allowed source domain '{parsed_base.hostname}'"
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
    max_bytes: int = 50 * 1024 * 1024,
    timeout_seconds: float = 30.0,
) -> tuple[int, dict[str, str], Generator[bytes, None, None]]:
    """
    Safely fetches a URL with source policy checks, SSRF checks, timeout, and streaming size limits.
    """
    if source_id:
        validate_source_policy(source_id, url)

    validate_url_host(url, require_https=False)  # allow http for testing mocks if specified

    headers = {
        "User-Agent": "MESA-Legal-Data/0.1 (+operator_contact)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.8",
    }

    client = httpx.Client(
        follow_redirects=True,
        max_redirects=3,
        timeout=httpx.Timeout(timeout_seconds),
        headers=headers,
    )

    try:
        req = client.build_request("GET", url)
        resp = client.send(req, stream=True)

        validate_url_host(str(resp.url), require_https=False)

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

    except httpx.TimeoutException as e:
        client.close()
        raise URLFetchError(f"Connection timeout: {e}") from e
    except httpx.HTTPError as e:
        client.close()
        raise URLFetchError(f"HTTP error: {e}") from e
