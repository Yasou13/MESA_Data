from pathlib import Path

import pytest
from pydantic import ValidationError

from mesa_legal_data.config import SettingsModel, load_settings, load_sources


def test_load_settings_defaults():
    settings = load_settings()
    assert settings.data_root == "/storage/mesa-legal-data/data"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.http_proxy is None


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", "/custom/path")
    monkeypatch.setenv("MESA_DATA_ENVIRONMENT", "production")

    settings = load_settings()
    assert settings.data_root == "/custom/path"
    assert settings.environment == "production"


def test_path_expansion():
    settings = SettingsModel(data_root="~/some-data")
    expected = Path("~/some-data").expanduser().resolve()
    assert settings.data_root_path == expected


def test_unknown_config_field_raises_error():
    with pytest.raises(ValidationError):
        SettingsModel(unknown_field="value")


def test_load_sources(tmp_path):
    yaml_content = """
version: "1.0.0"
sources:
  test_source:
    name: "Test Source"
    authority: "Test Auth"
    base_url: "https://test.com"
    access_mode: "manual"
    enabled: true
    families: ["legislation"]
    source_role: "test_role"
    policy_version: "1.0.0"
    http:
      user_agent: "Test"
      concurrency: 1
      min_interval_seconds: 1
      timeout_seconds: 10
      retries: 3
      max_requests_per_run: 5
      max_download_bytes: 1000
    allowed_content_types: ["text/html"]
"""
    config_file = tmp_path / "sources.yaml"
    config_file.write_text(yaml_content)

    sources_config = load_sources(config_file)
    assert sources_config.version == "1.0.0"
    assert "test_source" in sources_config.sources
    assert sources_config.sources["test_source"].http.timeout_seconds == 10


def test_secret_not_logged():
    settings = SettingsModel(operator_contact="secret_email@test.com")
    dumped = settings.dump_safe()
    assert dumped["operator_contact"] == "secret_email@test.com"
