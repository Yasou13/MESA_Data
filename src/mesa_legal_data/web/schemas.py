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
