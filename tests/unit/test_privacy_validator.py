from mesa_legal_data.validators.privacy import is_valid_tc_kimlik, scan_privacy_issues


def test_tc_kimlik_validation():
    # Synthetic valid TCKN algorithm example: 10000000146
    assert is_valid_tc_kimlik("10000000146") is True
    assert is_valid_tc_kimlik("10000000000") is False


def test_privacy_issue_scanning():
    text = "İletişim: 10000000146 numaralı kimlik ve test@example.com e-posta adresi."
    issues = scan_privacy_issues(text)

    codes = [i["code"] for i in issues]
    assert "PRIVACY_TCKN_DETECTED" in codes
    assert "PRIVACY_EMAIL_DETECTED" in codes

    for i in issues:
        assert "match" not in i
        assert "masked" in i
        assert "match_sha256" in i
