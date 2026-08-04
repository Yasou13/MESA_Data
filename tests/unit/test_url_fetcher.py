import pytest
import respx

from mesa_legal_data.sources.url_fetcher import (
    SourcePolicyError,
    SSRFError,
    fetch_url_stream,
    validate_url_host,
)


def test_private_ip_ssrf_blocking():
    with pytest.raises(SSRFError):
        fetch_url_stream("https://127.0.0.1/secret", require_https=True)

    with pytest.raises(SSRFError):
        fetch_url_stream("https://192.168.1.1/admin", require_https=True)

    with pytest.raises(SSRFError):
        fetch_url_stream("https://10.0.0.1/internal", require_https=True)

    with pytest.raises(SSRFError):
        fetch_url_stream("https://localhost/test", require_https=True)


def test_validate_url_host_http_rejected():
    with pytest.raises(SSRFError, match="URL scheme must be HTTPS"):
        validate_url_host("http://www.mevzuat.gov.tr/doc.pdf", require_https=True)


def test_validate_url_host_metadata_ip_rejected():
    with pytest.raises(SSRFError, match="forbidden"):
        validate_url_host("https://169.254.169.254/latest/meta-data", require_https=True)


@respx.mock
def test_private_ip_redirect_never_requested():
    """
    Ensures that if a safe URL redirects to a private IP (e.g. 127.0.0.1 or 169.254.169.254),
    validation fails BEFORE any HTTP request is sent to the private IP target.
    """
    initial_url = "https://www.mevzuat.gov.tr/redirect-to-private"
    private_target_url = "https://127.0.0.1/internal-secret"

    respx.get(initial_url).respond(status_code=302, headers={"Location": private_target_url})
    private_route = respx.get(private_target_url).respond(status_code=200, text="SECRET DATA")

    with pytest.raises(SSRFError):
        fetch_url_stream(
            url=initial_url,
            source_id="mevzuat",
            document_family="legislation",
            require_https=True,
        )

    assert not private_route.called


@respx.mock
def test_redirect_to_disallowed_domain_rejected():
    initial_url = "https://www.mevzuat.gov.tr/redirect-external"
    external_target_url = "https://attacker.example/malicious.pdf"

    respx.get(initial_url).respond(status_code=302, headers={"Location": external_target_url})
    ext_route = respx.get(external_target_url).respond(status_code=200, text="MALICIOUS")

    with pytest.raises(SourcePolicyError):
        fetch_url_stream(
            url=initial_url,
            source_id="mevzuat",
            document_family="legislation",
            require_https=True,
        )

    assert not ext_route.called


@respx.mock
def test_redirect_loop_rejected():
    url_a = "https://www.mevzuat.gov.tr/page-a"
    url_b = "https://www.mevzuat.gov.tr/page-b"

    respx.get(url_a).respond(status_code=302, headers={"Location": url_b})
    respx.get(url_b).respond(status_code=302, headers={"Location": url_a})

    with pytest.raises(SSRFError, match="Redirect loop"):
        fetch_url_stream(
            url=url_a,
            source_id="mevzuat",
            document_family="legislation",
            require_https=True,
        )


@respx.mock
def test_url_fetch_success():
    respx.get("https://www.mevzuat.gov.tr/law.pdf").respond(
        status_code=200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-1.4\nTest PDF content",
    )

    status, headers, stream_gen = fetch_url_stream(
        "https://www.mevzuat.gov.tr/law.pdf",
        source_id="mevzuat",
        document_family="legislation",
        require_https=True,
    )
    assert status == 200
    assert headers["content-type"] == "application/pdf"

    content = b"".join(list(stream_gen))
    assert content == b"%PDF-1.4\nTest PDF content"
