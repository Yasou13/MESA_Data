import pytest

from mesa_legal_data.sources.url_fetcher import (
    SourcePolicyError,
    validate_source_policy,
)


def test_source_policy_disabled_source():
    # Yargitay is set to enabled: false in sources.yaml
    with pytest.raises(SourcePolicyError, match="disabled"):
        validate_source_policy("yargitay", "https://karararama.yargitay.gov.tr/1")


def test_source_policy_domain_mismatch():
    with pytest.raises(SourcePolicyError, match="domain"):
        validate_source_policy("mevzuat", "https://malicious-site.com/test.pdf")


def test_source_policy_valid():
    # Mevzuat is enabled and base_url is https://www.mevzuat.gov.tr/
    validate_source_policy("mevzuat", "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf")
