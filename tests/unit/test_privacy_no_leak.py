from mesa_legal_data.validators.privacy import scan_privacy_issues


def test_privacy_no_raw_pii_leak():
    raw_tc = "10000000146"
    raw_email = "test.user@example.com"
    text = f"Kullanıcı TCKN: {raw_tc}, E-posta: {raw_email}"

    issues = scan_privacy_issues(text)
    assert len(issues) >= 2

    for issue in issues:
        message = issue["message"]
        masked = issue["masked"]
        # Assert raw TCKN and raw email username are NOT present in unmasked form in issues
        assert raw_tc not in message
        assert raw_tc not in masked
        assert "test.user@" not in message
        assert "test.user@" not in masked
