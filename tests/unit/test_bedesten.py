import base64
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from mesa_legal_data.catalog import get_connection, migrate
from mesa_legal_data.cli import app
from mesa_legal_data.parsers.decision import parse_decision_text
from mesa_legal_data.sources import request_control
from mesa_legal_data.sources.url_fetcher import URLFetchError

FIXTURES = Path(__file__).parents[1] / "golden" / "bedesten"
BASE_URL = "https://bedesten.adalet.gov.tr/emsal-karar/"


def fixture_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@respx.mock
def test_bedesten_search_import_pipeline_and_duplicate(tmp_path, monkeypatch):
    from mesa_legal_data.sources.bedesten import collect_bedesten

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_OPERATOR_CONTACT", "operator@mesa.test")
    migrate()
    search = fixture_json("search.json")
    search["data"]["emsalKararList"] = search["data"]["emsalKararList"][:2]
    times = []

    def search_response(request):
        payload = json.loads(request.content)
        assert payload["data"]["birimAdi"] == "Hukuk Genel Kurulu"
        assert payload["data"]["phrase"] == "Hukuk Genel Kurulu"
        assert payload["data"]["kararTarihiStart"] == "2021-01-01T00:00:00"
        assert payload["data"]["kararTarihiEnd"] == "2026-10-27T23:59:59"
        assert payload["data"]["pageSize"] == 2
        assert request.headers["AdaletApplicationName"] == "UyapMevzuat"
        assert "operator@mesa.test" in request.headers["User-Agent"]
        times.append(request_control.time_func())
        return httpx.Response(200, json=search)

    def content_response(request):
        document_id = json.loads(request.content)["data"]["documentId"]
        data = fixture_json(f"document-{document_id}.json")
        # Conflicting text must not override the source's structured metadata.
        text = base64.b64decode(data["data"]["content"]).decode("utf-8")
        text += "<p>Esas No: 1999/1 Karar No: 1999/2 Karar Tarihi: 01.01.1999</p>"
        data["data"]["content"] = base64.b64encode(text.encode()).decode()
        times.append(request_control.time_func())
        return httpx.Response(200, json=data)

    respx.post(BASE_URL + "searchDocuments").mock(side_effect=search_response)
    respx.post(BASE_URL + "getDocumentContent").mock(side_effect=content_response)
    artifacts = collect_bedesten("HGK", date(2021, 1, 1), date(2026, 10, 27), limit=2)
    assert len(artifacts) == 2
    conn = get_connection()
    records = conn.execute(
        "SELECT canonical_path, canonical_line FROM records WHERE record_type = 'decision' ORDER BY record_id"
    ).fetchall()
    assert len(records) == 2
    parsed_records = [
        json.loads((tmp_path / row[0]).read_text(encoding="utf-8").splitlines()[row[1] - 1]) for row in records
    ]
    by_esas = {record["esas_no"]: record for record in parsed_records}
    for item in search["data"]["emsalKararList"]:
        record = by_esas[item["esasNo"]]
        assert record["id"] == (
            "tr:case-law:yargitay:hukuk-genel-kurulu:"
            + item["esasNo"].replace("/", "-")
            + ":"
            + item["kararNo"].replace("/", "-")
        )
        assert record["court"] == "YARGITAY"
        assert record["chamber"] == "Hukuk Genel Kurulu"
        assert record["karar_no"] == item["kararNo"]
        assert (
            record["decision_date"]
            == date.fromisoformat("-".join(reversed(item["kararTarihiStr"].split(".")))).isoformat()
        )
    version_dates = {row[0] for row in conn.execute("SELECT snapshot_date FROM versions")}
    assert version_dates == {"2026-10-01", "2026-09-23"}
    before = [
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("artifacts", "versions", "records")
    ]
    conn.close()
    repeated = collect_bedesten("HGK", date(2021, 1, 1), date(2026, 10, 27), limit=2)
    assert all(artifact.is_duplicate for artifact in repeated)
    conn = get_connection()
    assert [
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("artifacts", "versions", "records")
    ] == before
    conn.close()
    assert all(b - a >= 6 for a, b in zip(times, times[1:]))


@pytest.mark.parametrize("retry_succeeds", [True, False])
@respx.mock
def test_bedesten_429_waits_and_retries_once(tmp_path, monkeypatch, retry_succeeds):
    from mesa_legal_data.sources.bedesten import collect_bedesten

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_OPERATOR_CONTACT", "operator@mesa.test")
    migrate()
    times = []

    def response(request):
        times.append(request_control.time_func())
        if retry_succeeds and len(times) == 2:
            return httpx.Response(200, json={"data": {"emsalKararList": [], "total": 0}})
        return httpx.Response(429, headers={"Retry-After": "9"})

    route = respx.post(BASE_URL + "searchDocuments").mock(side_effect=response)
    if retry_succeeds:
        assert collect_bedesten("HGK", date(2021, 1, 1), limit=2) == []
    else:
        with pytest.raises(ValueError, match="429.*retry"):
            collect_bedesten("HGK", date(2021, 1, 1), limit=2)
    assert route.call_count == 2
    assert times[1] - times[0] >= 9


@pytest.mark.parametrize("failure", ["redirect", "mime", "base64", "private_host"])
@respx.mock
def test_bedesten_rejects_unsafe_responses(tmp_path, monkeypatch, mock_dns, failure):
    from mesa_legal_data.sources.bedesten import collect_bedesten

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_OPERATOR_CONTACT", "operator@mesa.test")
    migrate()
    search = fixture_json("search.json")
    search["data"]["emsalKararList"] = search["data"]["emsalKararList"][:1]
    search_route = respx.post(BASE_URL + "searchDocuments").respond(200, json=search)
    content = fixture_json("document-1231237100.json")
    if failure == "redirect":
        search_route.respond(302, headers={"Location": "https://attacker.example/steal"})
    elif failure == "mime":
        content["data"]["mimeType"] = "application/javascript"
    elif failure == "base64":
        content["data"]["content"] = "%%%invalid%%%"
    elif failure == "private_host":
        mock_dns("bedesten.adalet.gov.tr", "127.0.0.1")
    respx.post(BASE_URL + "getDocumentContent").respond(200, json=content)
    with pytest.raises((ValueError, URLFetchError)):
        collect_bedesten("HGK", date(2021, 1, 1), limit=1)
    conn = get_connection()
    assert conn.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 0
    conn.close()


def test_aym_esas_karar_sayisi():
    parsed = parse_decision_text(
        "ANAYASA MAHKEMESİ\nEsas Sayısı : 2025/123\nKarar Sayısı : 2026/42\nKarar Tarihi: 12.02.2026"
    )
    assert parsed.esas_no == "2025/123"
    assert parsed.karar_no == "2026/42"


@respx.mock
def test_bedesten_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("MESA_DATA_OPERATOR_CONTACT", "operator@mesa.test")
    migrate()
    respx.post(BASE_URL + "searchDocuments").respond(200, json={"data": {"emsalKararList": [], "total": 0}})
    result = CliRunner().invoke(app, ["collect", "bedesten", "--unit", "HGK", "--from", "2021-01-01", "--limit", "2"])
    assert result.exit_code == 0, result.output
