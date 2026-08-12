import ipaddress
import os
import socket
import ssl
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from mesa_legal_data.config import load_settings, load_sources
from mesa_legal_data.sources.request_control import (
    enforce_min_interval,
    get_source_request_state,
)


class URLFetchError(Exception):
    pass


class SSRFError(URLFetchError):
    pass


class SizeLimitExceededError(URLFetchError):
    pass


class SourcePolicyError(URLFetchError):
    pass


EXPECTED_GEOTRUST_INTERMEDIATE_FINGERPRINT = "c06e307f7cfc1d32fa72a4c033c87b90019af216f0775d64978a2eca6c8a230e"


def verify_ca_cert_fingerprint(cert_path: Path, expected_hex_sha256: str) -> bool:
    """
    Parses the PEM/DER certificate file at cert_path and asserts that its DER SHA-256 fingerprint
    matches expected_hex_sha256. Fails closed (returns False) on any mismatch or corruption.
    """
    try:
        content = cert_path.read_bytes()
        import base64
        import hashlib

        der_bytes: bytes
        if b"-----BEGIN CERTIFICATE-----" in content:
            lines = [
                line.strip()
                for line in content.decode("utf-8", errors="ignore").splitlines()
                if line.strip() and not line.startswith("-----")
            ]
            der_bytes = base64.b64decode("".join(lines))
        else:
            der_bytes = content

        computed = hashlib.sha256(der_bytes).hexdigest().lower()
        clean_expected = expected_hex_sha256.replace(":", "").lower()
        return computed == clean_expected
    except Exception:
        return False


def get_packaged_intermediate_ca_path() -> Path | None:
    """
    Locates the packaged GeoTrust TLS RSA CA G1 intermediate certificate.
    Uses importlib.resources with a fallback to relative package file path.
    Verifies that the file exists and its SHA-256 fingerprint matches EXPECTED_GEOTRUST_INTERMEDIATE_FINGERPRINT.
    Fails closed if the certificate is corrupted, missing, or tampered.
    """
    try:
        import importlib.resources as pkg_resources

        certs_dir = pkg_resources.files("mesa_legal_data").joinpath("certs")
        cert_file = certs_dir.joinpath("geotrust_tls_rsa_ca_g1.pem")
        path = Path(str(cert_file))
        if path.is_file() and verify_ca_cert_fingerprint(path, EXPECTED_GEOTRUST_INTERMEDIATE_FINGERPRINT):
            return path
    except Exception:
        pass

    pkg_relative = Path(__file__).parent.parent / "certs" / "geotrust_tls_rsa_ca_g1.pem"
    if pkg_relative.is_file() and verify_ca_cert_fingerprint(pkg_relative, EXPECTED_GEOTRUST_INTERMEDIATE_FINGERPRINT):
        return pkg_relative

    return None


def build_ssl_context() -> ssl.SSLContext:
    """
    Builds a secure, additive SSLContext.
    Starts with default system/OS CA trust.
    If an explicit administrator override (SSL_CERT_FILE, REQUESTS_CA_BUNDLE, or CURL_CA_BUNDLE) is set, loads it.
    Additively loads the verified packaged intermediate CA certificate (GeoTrust TLS RSA CA G1) to bridge missing intermediate server chains.
    Enforces full TLS certificate validation and hostname verification.
    """
    import ssl

    ctx = ssl.create_default_context()

    ca_env = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
    if ca_env and os.path.exists(ca_env):
        ctx.load_verify_locations(cafile=ca_env)

    packaged_ca = get_packaged_intermediate_ca_path()
    if packaged_ca:
        ctx.load_verify_locations(cafile=str(packaged_ca))

    return ctx


@dataclass(frozen=True)
class ValidatedSourcePolicy:
    source_id: str
    document_family: str
    policy_version: str
    base_host: str
    allowed_hosts: frozenset[str]
    allowed_redirect_hosts: frozenset[str]
    allowed_content_types: frozenset[str]
    concurrency: int
    timeout_seconds: float
    retries: int
    max_requests_per_run: int
    max_download_bytes: int
    user_agent: str
    min_interval_seconds: float
    access_mode: str = "manual"


def normalize_media_type(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";", 1)[0].strip().lower() or None


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
    Production path strictly rejects non-HTTPS schemes and private/local IPs.
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

    if parsed.port and parsed.port != 443:
        raise SSRFError(f"Non-standard port {parsed.port} is forbidden: only HTTPS port 443 or default is allowed")

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


def get_source_input_policy(
    *,
    source_id: str,
    document_family: str,
    sources_yaml_path: Path | None = None,
    allow_disabled: bool = False,
) -> ValidatedSourcePolicy:
    """
    Central getter that loads and validates source input policy from sources.yaml.
    Enforces HTTP limit ranges and content type rules.
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
    if not allow_disabled and not source_info.enabled:
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
                raise SourcePolicyError(
                    f"USER_AGENT_INVALID: User-Agent '{source_info.http.user_agent}' contains unconfigured contact placeholder"
                )

    if int(source_info.http.concurrency) < 1:
        raise SourcePolicyError("HTTP limit invalid: concurrency must be >= 1")
    if int(source_info.http.max_requests_per_run) < 1:
        raise SourcePolicyError("HTTP limit invalid: max_requests_per_run must be >= 1")
    if float(source_info.http.timeout_seconds) <= 0:
        raise SourcePolicyError("HTTP limit invalid: timeout_seconds must be > 0")
    if int(source_info.http.retries) < 0:
        raise SourcePolicyError("HTTP limit invalid: retries must be >= 0")
    if int(source_info.http.max_download_bytes) <= 0:
        raise SourcePolicyError("HTTP limit invalid: max_download_bytes must be > 0")
    if float(source_info.http.min_interval_seconds) < 0:
        raise SourcePolicyError("HTTP limit invalid: min_interval_seconds must be >= 0")

    raw_mimes = getattr(source_info, "allowed_content_types", []) or []
    norm_mimes = set()
    for m in raw_mimes:
        n = normalize_media_type(m)
        if n:
            norm_mimes.add(n)

    if not norm_mimes:
        raise SourcePolicyError(
            f"SOURCE_ALLOWED_CONTENT_TYPES_EMPTY: Source '{source_id}' has empty allowed_content_types"
        )

    parsed_base = urlparse(source_info.base_url)
    if not parsed_base.hostname:
        raise SourcePolicyError(f"Bozuk source base_url: {source_info.base_url}")

    try:
        base_host_norm = parsed_base.hostname.lower().rstrip(".").encode("idna").decode("ascii")
    except Exception as e:
        raise SourcePolicyError(f"Invalid base_url IDNA hostname '{parsed_base.hostname}': {e}") from e

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

    policy_ver = str(getattr(source_info, "policy_version", getattr(sources_cfg, "version", "1.0.0")))

    return ValidatedSourcePolicy(
        source_id=source_id,
        document_family=document_family,
        policy_version=policy_ver,
        base_host=base_host_norm,
        allowed_hosts=frozenset(allowed_hosts_set),
        allowed_redirect_hosts=frozenset(allowed_redirect_set),
        allowed_content_types=frozenset(norm_mimes),
        concurrency=int(source_info.http.concurrency),
        timeout_seconds=float(source_info.http.timeout_seconds),
        retries=int(source_info.http.retries),
        max_requests_per_run=int(source_info.http.max_requests_per_run),
        max_download_bytes=int(source_info.http.max_download_bytes),
        user_agent=str(source_info.http.user_agent),
        min_interval_seconds=float(source_info.http.min_interval_seconds),
        access_mode=str(getattr(source_info, "access_mode", "manual")),
    )


def validate_source_request(
    *,
    source_id: str,
    document_family: str,
    url: str,
    is_redirect: bool = False,
    sources_yaml_path: Path | None = None,
) -> ValidatedSourcePolicy:
    """
    Central source policy validator for URL requests.
    Enforces host allowlist and SSRF safety.
    """
    policy = get_source_input_policy(
        source_id=source_id,
        document_family=document_family,
        sources_yaml_path=sources_yaml_path,
        allow_disabled=False,
    )

    parsed_url = urlparse(url)
    if parsed_url.scheme != "https":
        raise SSRFError(f"URL scheme must be HTTPS, got: {parsed_url.scheme}")

    if not parsed_url.hostname:
        raise SourcePolicyError("Invalid URL: missing hostname")

    try:
        host_norm = parsed_url.hostname.lower().rstrip(".").encode("idna").decode("ascii")
    except Exception as e:
        raise SourcePolicyError(f"Invalid IDNA hostname '{parsed_url.hostname}': {e}") from e

    check_literal_ip_safety(host_norm)

    if is_redirect:
        valid_set = policy.allowed_hosts | policy.allowed_redirect_hosts
    else:
        valid_set = policy.allowed_hosts

    if host_norm not in valid_set:
        raise SourcePolicyError(
            f"SOURCE_HOST_NOT_ALLOWED: URL domain '{parsed_url.hostname}' does not match allowed source domain '{policy.base_host}'"
        )

    return policy


def validate_source_policy(
    source_id: str,
    url: str,
    document_family: str | None = None,
    sources_yaml_path: Path | None = None,
):
    """
    Backwards-compatible wrapper.
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
    max_bytes: int | None = None,
    timeout_seconds: float | None = None,
    sources_yaml_path: Path | None = None,
) -> tuple[int, dict[str, str], Generator[bytes, None, None]]:
    """
    Safely fetches a URL with mandatory source policy, concurrency semaphore, rate limiting, request budget,
    SSRF checks, policy timeout, Content-Type validation, and streaming size limits.
    """
    policy = validate_source_request(
        source_id=source_id,
        document_family=document_family,
        url=url,
        is_redirect=False,
        sources_yaml_path=sources_yaml_path,
    )

    # Policy override restriction: override parameters cannot increase policy limit
    eff_max_bytes = min(policy.max_download_bytes, max_bytes) if max_bytes is not None else policy.max_download_bytes
    eff_timeout = (
        min(policy.timeout_seconds, timeout_seconds) if timeout_seconds is not None else policy.timeout_seconds
    )
    settings = load_settings()
    contact = ""
    try:
        raw_c = getattr(settings, "operator_contact", "")
        if raw_c:
            contact = str(raw_c).strip()
    except Exception:
        contact = ""

    placeholder_contacts = {
        "test@example.com",
        "example.com",
        "operator@example.com",
        "placeholder",
        "admin@example.com",
        "foo@bar.com",
    }

    if policy.access_mode != "manual":
        if settings.environment == "production":
            if not contact or contact.lower() in placeholder_contacts:
                raise SourcePolicyError(
                    f"OPERATOR_CONTACT_INVALID: Valid operator contact is required in production (got '{contact}')"
                )
        elif contact and contact.lower() in placeholder_contacts:
            raise SourcePolicyError(f"OPERATOR_CONTACT_INVALID: Placeholder contact '{contact}' is not allowed")

    eff_ua = policy.user_agent
    if contact and contact not in eff_ua:
        eff_ua = f"{eff_ua} (+{contact})"

    retries = policy.retries

    req_state = get_source_request_state(policy.source_id, policy.concurrency)
    from mesa_legal_data.sources.request_control import get_run_budget

    budget = get_run_budget(policy.source_id, policy.max_requests_per_run)

    current_url = url
    visited: set[str] = set()
    MAX_REDIRECTS = 3

    client = httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(eff_timeout),
        verify=build_ssl_context(),
        headers={
            "User-Agent": eff_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.8",
        },
    )

    req_state.semaphore.acquire()
    acquired = True

    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            if current_url in visited:
                raise SSRFError(f"Redirect loop detected for URL: {current_url}")
            visited.add(current_url)

            parsed_curr = urlparse(current_url)
            if parsed_curr.scheme != "https":
                raise SSRFError(f"URL scheme must be HTTPS, got: {parsed_curr.scheme}")

            if parsed_curr.hostname:
                check_literal_ip_safety(parsed_curr.hostname.lower().rstrip("."))

            is_red = redirect_count > 0
            validate_source_request(
                source_id=source_id,
                document_family=document_family,
                url=current_url,
                is_redirect=is_red,
                sources_yaml_path=sources_yaml_path,
            )

            validate_url_host(current_url)

            resp = None
            for attempt in range(retries + 1):
                enforce_min_interval(req_state, policy.min_interval_seconds)
                budget.consume()

                try:
                    req = client.build_request("GET", current_url)
                    resp = client.send(req, stream=True)

                    if resp.status_code == 429 and attempt < retries:
                        retry_after = resp.headers.get("retry-after")
                        delay = 1.0
                        if retry_after and retry_after.isdigit():
                            delay = min(float(retry_after), 60.0)
                        resp.close()
                        time.sleep(delay)
                        continue

                    if resp.status_code in (502, 503, 504) and attempt < retries:
                        resp.close()
                        continue

                    break
                except (httpx.TimeoutException, httpx.ConnectError) as exc:
                    if attempt < retries:
                        continue
                    raise URLFetchError(f"HTTP connection failed after {retries} retries: {exc}") from exc

            if resp is None:
                raise URLFetchError("HTTP request failed")

            if resp.status_code in (301, 302, 303, 307, 308):
                if redirect_count >= MAX_REDIRECTS:
                    resp.close()
                    raise URLFetchError(f"Too many redirects (max {MAX_REDIRECTS})")

                location = resp.headers.get("Location") or resp.headers.get("location")
                resp.close()
                if not location:
                    raise URLFetchError("Redirect status received without Location header")

                current_url = urljoin(current_url, location)
                continue

            if resp.status_code != 200:
                resp.close()
                raise URLFetchError(f"HTTP status {resp.status_code}")

            # Pre-download Content-Length check
            cl_header = resp.headers.get("content-length")
            if cl_header and cl_header.isdigit():
                if int(cl_header) > eff_max_bytes:
                    resp.close()
                    raise SizeLimitExceededError(
                        f"Header Content-Length ({cl_header}) exceeds limit of {eff_max_bytes} bytes"
                    )

            # Pre-download Content-Type check
            raw_ct = resp.headers.get("content-type")
            decl_mime = normalize_media_type(raw_ct)
            if decl_mime and decl_mime not in ("application/octet-stream", "binary/octet-stream"):
                if decl_mime not in policy.allowed_content_types:
                    resp.close()
                    raise SourcePolicyError(
                        f"SOURCE_CONTENT_TYPE_NOT_ALLOWED: Content-Type '{decl_mime}' not allowed for source '{source_id}'"
                    )

            def stream_generator():
                nonlocal acquired
                downloaded = 0
                try:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        downloaded += len(chunk)
                        if downloaded > eff_max_bytes:
                            raise SizeLimitExceededError(f"Download size exceeded max limit of {eff_max_bytes} bytes")
                        yield chunk
                finally:
                    resp.close()
                    client.close()
                    if acquired:
                        req_state.semaphore.release()
                        acquired = False

            headers_dict = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status_code, headers_dict, stream_generator()

        raise URLFetchError("Too many redirects")
    except Exception:
        client.close()
        if acquired:
            req_state.semaphore.release()
            acquired = False
        raise


def fetch_discovery_html(
    source_id: str,
    family: str,
    url: str,
    sources_yaml_path: Path | None = None,
) -> str:
    """
    Fetches discovery HTML content safely enforcing source policy, allowed hosts,
    SSRF resolution checks, rate limiting, and size bounds without creating raw storage artifacts.
    """
    status_code, headers, stream_gen = fetch_url_stream(
        url=url,
        source_id=source_id,
        document_family=family,
        sources_yaml_path=sources_yaml_path,
    )

    if status_code != 200:
        raise URLFetchError(f"Discovery HTTP request returned status code {status_code}")

    chunks = []
    total_bytes = 0
    max_bytes = 10 * 1024 * 1024  # 10 MB limit for discovery HTML page

    for chunk in stream_gen:
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise SizeLimitExceededError(f"Discovery HTML size {total_bytes} exceeds limit {max_bytes}")
        chunks.append(chunk)

    raw_bytes = b"".join(chunks)

    ct = headers.get("content-type", "").lower()
    if ct and not ("html" in ct or "text" in ct or "xml" in ct):
        raise SourcePolicyError(f"Discovery page returned invalid Content-Type: {ct}")

    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("iso-8859-9", errors="ignore")
