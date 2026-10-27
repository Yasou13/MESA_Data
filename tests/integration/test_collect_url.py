import pytest
import respx
from typer.testing import CliRunner

from mesa_legal_data.catalog import get_db_path, migrate
from mesa_legal_data.sources.manual import import_manual_url
from mesa_legal_data.sources.url_fetcher import SourcePolicyError

runner = CliRunner()


def test_collect_url_disabled_source_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    sources_yaml_path = tmp_path / "sources.yaml"
    sources_yaml_path.write_text(
        'version: "1.0.0"\n'
        "sources:\n"
        "  yargitay:\n"
        "    name: Disabled Yargitay\n"
        "    authority: Yargitay\n"
        "    base_url: https://karararama.yargitay.gov.tr/\n"
        "    access_mode: manual\n"
        "    enabled: false\n"
        "    families: [decision]\n"
        "    source_role: official_case_law\n"
        '    policy_version: "1.0.0"\n'
        "    http: {user_agent: MESA-Legal-Data-Test/1.0}\n"
        "    allowed_content_types: [text/html]\n",
        encoding="utf-8",
    )
    with pytest.raises(SourcePolicyError, match="SOURCE_DISABLED"):
        import_manual_url(
            url="https://karararama.yargitay.gov.tr/doc.html",
            source_id="yargitay",
            document_id="tr:case-law:yargitay:2026:1",
            family="decision",
            sources_yaml_path=sources_yaml_path,
        )


def test_collect_url_wrong_domain_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    with pytest.raises(SourcePolicyError, match="does not match allowed source domain"):
        import_manual_url(
            url="https://attacker.example/doc.pdf",
            source_id="mevzuat",
            document_id="tr:legislation:law:4721",
            family="legislation",
        )


@respx.mock
def test_collect_url_success(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    url = "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf"
    respx.get(url).respond(
        status_code=200,
        headers={"content-type": "application/pdf"},
        content=b"%PDF-1.4\nSynthetic Law PDF",
    )

    art = import_manual_url(
        url=url,
        source_id="mevzuat",
        document_id="tr:legislation:constitution:2709",
        family="legislation",
        title="Anayasa",
    )

    assert art.artifact_id.startswith("sha256:")
    assert art.document_id == "tr:legislation:constitution:2709"
