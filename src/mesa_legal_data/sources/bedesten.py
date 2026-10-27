"""Collect the scoped Yargıtay boards through Bedesten's JSON endpoints."""

import base64
import binascii
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from mesa_legal_data.config import load_settings
from mesa_legal_data.ids import build_decision_id
from mesa_legal_data.models import FetchedArtifact
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.sources import request_control
from mesa_legal_data.sources.manual import import_manual_file
from mesa_legal_data.sources.url_fetcher import (
    build_ssl_context,
    detect_html_error_page,
    validate_source_request,
    validate_url_host,
)

BASE_URL = "https://bedesten.adalet.gov.tr/emsal-karar/"
UNITS = {
    "HGK": "Hukuk Genel Kurulu",
    "CGK": "Ceza Genel Kurulu",
    "IBK": "İçtihatları Birleştirme Kurulu",
}


def _post(endpoint: str, data: dict, *, paging: bool = False) -> dict:
    url = BASE_URL + endpoint
    policy = validate_source_request(source_id="yargitay", document_family="decision", url=url)
    validate_url_host(url)
    contact = load_settings().operator_contact.strip()
    if not contact or contact.lower() in {
        "test@example.com",
        "example.com",
        "operator@example.com",
        "placeholder",
        "admin@example.com",
        "foo@bar.com",
    }:
        raise ValueError("OPERATOR_CONTACT_MISSING: configure a valid operator_contact for Bedesten")
    user_agent = policy.user_agent
    if contact not in user_agent:
        user_agent += f" (+{contact})"
    payload: dict = {"data": data, "applicationName": "UyapMevzuat"}
    if paging:
        payload["paging"] = True
    state = request_control.get_source_request_state("yargitay", policy.concurrency)
    budget = request_control.get_run_budget("yargitay", policy.max_requests_per_run)
    # JSON contains base64, whose size is at most 4/3 of the decoded file, plus metadata.
    max_response = 4 * ((policy.max_download_bytes + 2) // 3) + 1024 * 1024
    with (
        state.semaphore,
        httpx.Client(
            verify=build_ssl_context(),
            follow_redirects=False,
            timeout=policy.timeout_seconds,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "AdaletApplicationName": "UyapMevzuat",
                "Origin": "https://mevzuat.adalet.gov.tr",
                "Referer": "https://mevzuat.adalet.gov.tr/",
            },
        ) as client,
    ):
        for attempt in range(2):
            request_control.enforce_min_interval(state, max(6, policy.min_interval_seconds))
            budget.consume()
            with client.stream("POST", url, json=payload) as response:
                if response.status_code == 429:
                    if attempt:
                        raise ValueError("Bedesten HTTP 429 after one retry; collection stopped")
                    retry_after = response.headers.get("retry-after", "")
                    delay = min(float(retry_after), 60) if retry_after.isdigit() else 6
                else:
                    if response.status_code != 200:
                        raise ValueError(f"Bedesten HTTP {response.status_code}; collection stopped")
                    if response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                        raise ValueError("Bedesten response is not application/json")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response:
                            raise ValueError("Bedesten response exceeds source download size limit")
                    result = json.loads(body)
                    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
                        raise ValueError(
                            f"Bedesten API error: {result.get('metadata') if isinstance(result, dict) else result}"
                        )
                    return result["data"]
            request_control.sleep_func(delay)
    raise ValueError("Bedesten request failed")


def collect_bedesten(
    unit: str,
    from_date: date,
    to_date: date | None = None,
    *,
    limit: int = 10,
) -> list[FetchedArtifact]:
    if unit not in UNITS:
        raise ValueError("Unit must be HGK, CGK or IBK")
    end = to_date or datetime.now(ZoneInfo("Europe/Istanbul")).date()
    if limit < 1 or from_date < date(2021, 1, 1) or end < from_date:
        raise ValueError("Use a positive limit and a date range starting on or after 2021-01-01")
    request_control.reset_run_budget("yargitay")
    artifacts: list[FetchedArtifact] = []
    page = 1
    page_size = min(10, limit)
    while len(artifacts) < limit:
        data = _post(
            "searchDocuments",
            {
                "pageSize": page_size,
                "pageNumber": page,
                "itemTypeList": ["YARGITAYKARARI"],
                # Empty phrases are rejected. The unit name occurs in decision headings.
                "phrase": UNITS[unit],
                "birimAdi": UNITS[unit],
                "kararTarihiStart": from_date.isoformat() + "T00:00:00",
                "kararTarihiEnd": end.isoformat() + "T23:59:59",
                "sortFields": ["KARAR_TARIHI"],
                "sortDirection": "desc",
            },
            paging=True,
        )
        items = data.get("emsalKararList", [])
        if not items:
            break
        for item in items[: limit - len(artifacts)]:
            if item["birimAdi"] != UNITS[unit]:
                raise ValueError("Bedesten returned a decision outside the requested unit")
            # Bedesten timestamps are UTC; the displayed date is the Turkish legal date.
            if item.get("kararTarihiStr"):
                decision_date = datetime.strptime(item["kararTarihiStr"], "%d.%m.%Y").date()
            else:
                decision_date = (
                    datetime.fromisoformat(item["kararTarihi"].replace("Z", "+00:00"))
                    .astimezone(ZoneInfo("Europe/Istanbul"))
                    .date()
                )
            if not from_date <= decision_date <= end:
                raise ValueError("Bedesten returned a decision outside the requested dates")
            doc_id = build_decision_id("YARGITAY", item["birimAdi"], item["esasNo"], item["kararNo"], "")
            metadata = {
                "court": "YARGITAY",
                "chamber": item["birimAdi"],
                "esas_no": item["esasNo"],
                "karar_no": item["kararNo"],
                "decision_date": decision_date.isoformat(),
                "bedesten_document_id": item["documentId"],
            }
            content = _post("getDocumentContent", {"documentId": item["documentId"]})
            policy = validate_source_request(
                source_id="yargitay",
                document_family="decision",
                url=BASE_URL + "getDocumentContent",
            )
            mime = content.get("mimeType", "").split(";")[0].strip().lower()
            if mime not in policy.allowed_content_types or mime not in {"text/html", "application/pdf"}:
                raise ValueError(f"Bedesten document MIME is not allowed: {mime}")
            try:
                raw = base64.b64decode(content["content"], validate=True)
            except (binascii.Error, KeyError, TypeError) as exc:
                raise ValueError("Bedesten returned invalid base64 document content") from exc
            if not raw or len(raw) > policy.max_download_bytes:
                raise ValueError("Bedesten document is empty or exceeds source download size limit")
            if mime == "text/html" and (error := detect_html_error_page(raw.decode("utf-8", errors="replace"))):
                raise ValueError(error)
            with tempfile.TemporaryDirectory(prefix="mesa-bedesten-") as temp:
                file = Path(temp) / ("decision.pdf" if mime == "application/pdf" else "decision.html")
                file.write_bytes(raw)
                artifact = import_manual_file(
                    file_path=file,
                    source_id="yargitay",
                    family="decision",
                    document_type="yargitay_decision",
                    document_id=doc_id,
                    title=f"{item['birimAdi']} {item['esasNo']} E., {item['kararNo']} K.",
                    extra_metadata=metadata,
                )
            status = "skipped" if artifact.is_duplicate else process_artifact_pipeline(artifact.artifact_id)
            print(f"{doc_id}: {'unchanged' if artifact.is_duplicate else 'collected'}, pipeline: {status}")
            artifacts.append(artifact)
        if page * page_size >= data.get("total", page * page_size + 1):
            break
        page += 1
    return artifacts
