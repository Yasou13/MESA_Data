from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ApiResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    data: Optional[Any] = None
    error: Optional[ApiErrorDetail] = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=2, max_length=100)
    note: Optional[str] = Field(default=None, max_length=2000)


class ReleaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]+$",
    )


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=2000)


class UrlImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    url: str
    document_id: str
    family: str = Field(default="legislation")
    document_type: str = Field(default="law")
    jurisdiction: str = Field(default="TR")
    title: Optional[str] = Field(default=None)


class HarvestStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = "resmi_gazete"
    start_date: Optional[str] = None
    document_types: Optional[list[str]] = None


class IssueResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(default="resolved")
    resolved_by: str = Field(default="web-user")
    resolution_note: Optional[str] = Field(default=None, max_length=2000)


class SourceSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    auto_approval_enabled: bool = False
    weekly_sample_count: int = Field(default=10, ge=0, le=1000)


class ParserCertifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parser_name: str = Field(min_length=1, max_length=100)
    parser_version: str = Field(min_length=1, max_length=50)
    certified: bool = True
    certified_by: Optional[str] = Field(default="operator", max_length=100)


class MesaTargetSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=5, max_length=500)
    tenant_id: str = Field(min_length=1, max_length=100)
    workspace_id: str = Field(min_length=1, max_length=100)
    dataset_id: str = Field(min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=100)
    content_limit_chars: int = Field(default=32768, ge=1024, le=32768)
    health_path: str = Field(default="/health", max_length=300, pattern=r"^/.*$")
    session_start_path: str = Field(default="/v4/sessions/start", max_length=300, pattern=r"^/.*$")
    publish_path: str = Field(default="/v4/memory/insert", max_length=300, pattern=r"^/.*$")
    mutation_status_path_template: str = Field(default="/v4/mutations/{mutation_id}", max_length=300, pattern=r"^/.*$")
    session_end_path_template: str = Field(default="/v4/sessions/{session_id}/end", max_length=300, pattern=r"^/.*$")


class MesaPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_key: str = Field(default="default")
    release_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]+$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_config_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
