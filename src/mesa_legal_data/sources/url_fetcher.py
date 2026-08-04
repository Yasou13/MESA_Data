import ipaddress
import socket
from urllib.parse import urlparse
import httpx
from typing import Generator


class URLFetchError(Exception):
    pass


class SSRFError(URLFetchError):
    pass


class SizeLimitExceededError(URLFetchError):
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


def validate_url_host(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Invalid URL: missing hostname")

    try:
        # Resolve hostname to IP addresses
        addr_info = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if is_ip_private(ip_str):
                raise SSRFError(f"Access to private/local IP {ip_str} ({hostname}) is forbidden")
    except socket.gaierror as e:
        raise URLFetchError(f"Could not resolve hostname {hostname}: {e}") from e


def fetch_url_stream(
    url: str,
    max_bytes: int = 100 * 1024 * 1024,
    timeout_seconds: float = 10.0,
) -> tuple[int, dict[str, str], Generator[bytes, None, None]]:
    """
    Safely fetches a URL with SSRF checks, timeout, and streaming size limits.
    Returns (status_code, headers, chunk_generator).
    """
    validate_url_host(url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.8",
    }

    client = httpx.Client(
        follow_redirects=True,
        max_redirects=5,
        timeout=httpx.Timeout(30.0),
        headers=headers,
    )

    try:
        req = client.build_request("GET", url)
        resp = client.send(req, stream=True)
        
        # Validate final URL after redirects for SSRF
        validate_url_host(str(resp.url))

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
