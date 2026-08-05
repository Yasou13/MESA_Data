import time

import pytest
import respx

from mesa_legal_data.sources.request_control import (
    RequestBudget,
    SourceRequestBudgetExceeded,
    SourceRequestState,
    enforce_min_interval,
)
from mesa_legal_data.sources.url_fetcher import (
    SizeLimitExceededError,
    SourcePolicyError,
    fetch_url_stream,
    get_source_input_policy,
)


def test_get_source_input_policy_valid():
    pol = get_source_input_policy(source_id="mevzuat", document_family="legislation")
    assert pol.source_id == "mevzuat"
    assert pol.concurrency >= 1
    assert pol.max_requests_per_run >= 1
    assert "text/html" in pol.allowed_content_types
    assert pol.policy_version == "1.0.0"


def test_get_source_input_policy_invalid_source():
    with pytest.raises(SourcePolicyError, match="SOURCE_NOT_FOUND"):
        get_source_input_policy(source_id="nonexistent_source", document_family="legislation")


def test_request_budget_exceeded():
    budget = RequestBudget(max_requests=2)
    budget.consume()
    budget.consume()
    with pytest.raises(SourceRequestBudgetExceeded):
        budget.consume()


def test_enforce_min_interval():
    state = SourceRequestState(concurrency_limit=1)
    start = time.monotonic()
    enforce_min_interval(state, min_interval_seconds=0.1)
    enforce_min_interval(state, min_interval_seconds=0.1)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08


@respx.mock
def test_content_length_pre_check_exceeded():
    respx.get("https://www.mevzuat.gov.tr/large.pdf").respond(
        status_code=200,
        headers={"content-length": "999999999", "content-type": "application/pdf"},
        content=b"test",
    )
    with pytest.raises(SizeLimitExceededError, match="Header Content-Length"):
        fetch_url_stream(
            url="https://www.mevzuat.gov.tr/large.pdf",
            source_id="mevzuat",
            document_family="legislation",
        )


@respx.mock
def test_disallowed_content_type_pre_check():
    respx.get("https://www.mevzuat.gov.tr/script.exe").respond(
        status_code=200,
        headers={"content-type": "application/x-msdownload"},
        content=b"binary",
    )
    with pytest.raises(SourcePolicyError, match="SOURCE_CONTENT_TYPE_NOT_ALLOWED"):
        fetch_url_stream(
            url="https://www.mevzuat.gov.tr/script.exe",
            source_id="mevzuat",
            document_family="legislation",
        )


@respx.mock
def test_override_cannot_exceed_policy_limit():
    pol = get_source_input_policy(source_id="mevzuat", document_family="legislation")
    respx.get("https://www.mevzuat.gov.tr/over.pdf").respond(
        status_code=200,
        headers={"content-length": str(pol.max_download_bytes + 100), "content-type": "application/pdf"},
        content=b"test",
    )
    with pytest.raises(SizeLimitExceededError):
        # Even if caller passes a huge max_bytes, effective limit remains bounded by policy
        fetch_url_stream(
            url="https://www.mevzuat.gov.tr/over.pdf",
            source_id="mevzuat",
            document_family="legislation",
            max_bytes=pol.max_download_bytes * 10,
        )
