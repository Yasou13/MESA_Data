import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from mesa_legal_data.sources.url_fetcher import (
    fetch_url_stream,
    SSRFError,
    URLFetchError,
    SizeLimitExceededError,
)
from mesa_legal_data.cli import app

runner = CliRunner()

def test_private_ip_ssrf_blocking():
    with pytest.raises(SSRFError):
        fetch_url_stream("http://127.0.0.1/secret")

    with pytest.raises(SSRFError):
        fetch_url_stream("http://192.168.1.1/admin")

    with pytest.raises(SSRFError):
        fetch_url_stream("http://10.0.0.1/internal")

    with pytest.raises(SSRFError):
        fetch_url_stream("http://localhost/test")


@respx.mock
def test_url_fetch_success():
    respx.get("http://example.com/law.pdf").respond(
        status_code=200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-1.4\nTest PDF content",
    )

    status, headers, stream_gen = fetch_url_stream("http://example.com/law.pdf")
    assert status == 200
    assert headers["content-type"] == "application/pdf"

    content = b"".join(list(stream_gen))
    assert content == b"%PDF-1.4\nTest PDF content"


@respx.mock
def test_url_fetch_404():
    respx.get("http://example.com/missing.pdf").respond(status_code=404)

    with pytest.raises(URLFetchError, match="HTTP status 404"):
        fetch_url_stream("http://example.com/missing.pdf")


@respx.mock
def test_url_fetch_429():
    respx.get("http://example.com/rate.pdf").respond(status_code=429)

    with pytest.raises(URLFetchError, match="HTTP status 429"):
        fetch_url_stream("http://example.com/rate.pdf")


@respx.mock
def test_url_fetch_redirect():
    respx.get("http://example.com/old_location").respond(
        status_code=302,
        headers={"Location": "http://example.com/new_location"},
    )
    respx.get("http://example.com/new_location").respond(
        status_code=200,
        headers={"content-type": "text/html"},
        content=b"<!DOCTYPE html><html><body>Redirected</body></html>",
    )

    status, headers, stream_gen = fetch_url_stream("http://example.com/old_location")
    assert status == 200
    content = b"".join(list(stream_gen))
    assert b"Redirected" in content


@respx.mock
def test_url_fetch_max_size_exceeded():
    large_data = b"A" * 2000
    respx.get("http://example.com/big.file").respond(
        status_code=200,
        headers={"content-type": "text/plain"},
        content=large_data,
    )

    status, headers, stream_gen = fetch_url_stream("http://example.com/big.file", max_bytes=1000)
    with pytest.raises(SizeLimitExceededError):
        list(stream_gen)
