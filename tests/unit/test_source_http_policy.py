import pytest

from mesa_legal_data.config import SourceConfig, HttpConfig
from mesa_legal_data.sources.url_fetcher import (
    SourcePolicyError,
    SSRFError,
    validate_source_request,
)


def test_explicit_host_matching_no_auto_www():
    # Allowed host (mevzuat in sources.yaml)
    validate_source_request(
        url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4721.pdf",
        source_id="mevzuat",
        document_family="legislation",
    )

    # Subdomain without explicit allowlist entry must fail
    with pytest.raises(SourcePolicyError, match="SOURCE_HOST_NOT_ALLOWED"):
        validate_source_request(
            url="https://sub.mevzuat.gov.tr/doc.pdf",
            source_id="mevzuat",
            document_family="legislation",
        )


def test_user_agent_placeholder_check(monkeypatch, tmp_path):
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("""
version: "1.0.0"
sources:
  test_src:
    name: "Test"
    authority: "Test Auth"
    base_url: "https://www.mevzuat.gov.tr/"
    access_mode: "approved_web"
    enabled: true
    families: ["legislation"]
    source_role: "consolidated_text"
    policy_version: "1.0.0"
    http:
      user_agent: "MESA-Legal-Data/1.0 (+operator_contact)"
      concurrency: 1
      min_interval_seconds: 5
      timeout_seconds: 30
      retries: 3
      max_requests_per_run: 25
      max_download_bytes: 52428800
    allowed_content_types: ["text/html"]
    allowed_hosts: ["www.mevzuat.gov.tr"]
""")

    with pytest.raises(SourcePolicyError, match="USER_AGENT_INVALID"):
        validate_source_request(
            url="https://www.mevzuat.gov.tr/1.pdf",
            source_id="test_src",
            document_family="legislation",
            sources_yaml_path=sources_yaml,
        )
