from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DeliveryStatus(str, Enum):
    PLANNED = "PLANNED"
    SENDING = "SENDING"
    AWAITING_MUTATION = "AWAITING_MUTATION"
    COMMITTED = "COMMITTED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MutationState(str, Enum):
    PLANNED = "PLANNED"
    SENDING = "SENDING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_MUTATION = "AWAITING_MUTATION"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class MesaTargetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_key: str = Field(default="default")
    base_url: str = Field(default="")
    tenant_id: str = Field(default="default")
    workspace_id: str = Field(default="legal")
    dataset_id: str = Field(default="tr_legislation")
    agent_id: str = Field(default="mesa_data_publisher")
    content_limit_chars: int = Field(default=32768, ge=1024, le=1048576)
    contract_source: Literal["unknown", "configured", "live_verified"] = "unknown"
    health_path: str = ""
    publish_path: str = ""
    mutation_status_path_template: str = ""
    api_key_configured: bool = Field(default=False)
    updated_at: str | None = None


class SourceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    document_id: str
    version_id: str
    chunk_type: Literal["preamble", "article", "annex", "decision_header", "decision_body", "general"]
    title: str | None = None
    char_start: int
    char_end: int
    ordinal: int
    content: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PreflightCheckItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    status: Literal["PASS", "FAIL", "WARN"]
    message: str


class PreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overall_status: Literal["PASS", "FAIL"]
    checks: list[PreflightCheckItem]
    ready_documents_count: int
    ready_versions_count: int
    estimated_chunks_count: int
    total_canonical_bytes: int


class DeliveryPlanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready_documents: int
    ready_versions: int
    estimated_chunks: int
    total_canonical_bytes: int
    already_committed_chunks: int
    new_chunks_to_send: int
    blocked_versions_excluded: int
    unreadable_versions_excluded: int = 0
