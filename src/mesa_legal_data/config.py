from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageQuotaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active_data_limit_gb: float = 50.0
    raw_limit_gb: float = 25.0
    canonical_limit_gb: float = 10.0
    releases_limit_gb: float = 10.0
    tmp_limit_gb: float = 5.0
    minimum_free_space_gb: float = 20.0


class SettingsModel(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MESA_DATA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    data_root: str = Field(default="/storage/mesa-legal-data/data")
    mesa_staging_db: str = Field(default="/storage/mesa-legal-data/data/mesa_staging.sqlite")
    environment: Literal["development", "production", "testing"] = Field(default="development")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    operator_contact: str = Field(default="")
    http_proxy: str | None = Field(default=None)
    storage: StorageQuotaConfig = Field(default_factory=StorageQuotaConfig)

    @property
    def data_root_path(self) -> Path:
        path = Path(self.data_root).expanduser().resolve()
        return path

    def dump_safe(self) -> dict:
        data = self.model_dump()
        return data


class HttpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_agent: str
    concurrency: int
    min_interval_seconds: int
    timeout_seconds: int
    retries: int
    max_requests_per_run: int
    max_download_bytes: int


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    authority: str
    base_url: str
    access_mode: Literal["manual", "approved_web", "licensed_api"]
    enabled: bool
    families: list[str]
    source_role: str
    policy_version: str
    editorial_note_required: bool = False
    http: HttpConfig
    allowed_content_types: list[str]
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_redirect_hosts: list[str] = Field(default_factory=list)


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    sources: dict[str, SourceConfig]


def load_settings(settings_path: str | Path | None = None) -> SettingsModel:
    if settings_path:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return SettingsModel(**data.get("settings", {}))
    return SettingsModel()


def load_sources(sources_path: str | Path) -> SourcesConfig:
    with open(sources_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return SourcesConfig(**data)
