import pytest

from mesa_legal_data.sources.url_fetcher import SourcePolicyError, SSRFError, fetch_discovery_html


def test_discovery_safe_http_disallowed_host() -> None:
    # Attempting to run discovery on an unallowed host must be rejected by source policy
    with pytest.raises(SourcePolicyError):
        fetch_discovery_html(
            source_id="resmi_gazete",
            family="legislation",
            url="https://unauthorized-domain.com/index.html",
        )


def test_discovery_safe_http_non_https() -> None:
    # Non-HTTPS scheme must trigger SSRFError
    with pytest.raises(SSRFError):
        fetch_discovery_html(
            source_id="resmi_gazete",
            family="legislation",
            url="http://www.resmigazete.gov.tr/index.htm",
        )
