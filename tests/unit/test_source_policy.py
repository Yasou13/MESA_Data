import pytest

from mesa_legal_data.sources.url_fetcher import (
    SourcePolicyError,
    validate_source_policy,
    validate_url_host,
)


def test_source_policy_valid_enabled_source():
    # mevzuat is enabled and base_url is https://www.mevzuat.gov.tr/
    validate_source_policy(
        source_id="mevzuat",
        url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf",
        document_family="legislation",
    )


def test_source_policy_unknown_source():
    with pytest.raises(SourcePolicyError, match="SOURCE_NOT_FOUND"):
        validate_source_policy(
            source_id="unknown_source",
            url="https://www.mevzuat.gov.tr/doc.pdf",
            document_family="legislation",
        )


def test_source_policy_disabled_source():
    # yargitay is enabled: false in sources.yaml
    with pytest.raises(SourcePolicyError, match="SOURCE_DISABLED"):
        validate_source_policy(
            source_id="yargitay",
            url="https://karararama.yargitay.gov.tr/doc.html",
            document_family="decision",
        )


def test_source_policy_disallowed_family():
    # mevzuat only supports "legislation", not "decision"
    with pytest.raises(SourcePolicyError, match="SOURCE_FAMILY_NOT_ALLOWED"):
        validate_source_policy(
            source_id="mevzuat",
            url="https://www.mevzuat.gov.tr/doc.pdf",
            document_family="decision",
        )


def test_source_policy_wrong_domain():
    with pytest.raises(SourcePolicyError, match="does not match allowed source domain"):
        validate_source_policy(
            source_id="mevzuat",
            url="https://attacker.example/doc.pdf",
            document_family="legislation",
        )


def test_source_policy_lookalike_domain():
    with pytest.raises(SourcePolicyError, match="does not match allowed source domain"):
        validate_source_policy(
            source_id="mevzuat",
            url="https://mevzuat.gov.tr.attacker.example/doc.pdf",
            document_family="legislation",
        )


def test_url_userinfo_rejected():
    with pytest.raises(SourcePolicyError, match="userinfo"):
        validate_url_host("https://mevzuat.gov.tr@attacker.example/file.pdf")
