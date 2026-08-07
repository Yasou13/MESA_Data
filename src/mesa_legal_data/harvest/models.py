from dataclasses import dataclass
from datetime import date
from enum import Enum


class ItemStatus(str, Enum):
    DISCOVERED = "discovered"
    QUEUED = "queued"
    LEASED = "leased"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    DUPLICATE = "duplicate"
    RETRY_WAIT = "retry_wait"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


VALID_STATUS_TRANSITIONS: dict[ItemStatus, set[ItemStatus]] = {
    ItemStatus.DISCOVERED: {ItemStatus.QUEUED, ItemStatus.SKIPPED, ItemStatus.BLOCKED},
    ItemStatus.QUEUED: {ItemStatus.LEASED, ItemStatus.CANCELLED},
    ItemStatus.LEASED: {ItemStatus.DOWNLOADING, ItemStatus.QUEUED, ItemStatus.FAILED},
    ItemStatus.DOWNLOADING: {
        ItemStatus.DOWNLOADED,
        ItemStatus.RETRY_WAIT,
        ItemStatus.FAILED,
        ItemStatus.BLOCKED,
        ItemStatus.DUPLICATE,
    },
    ItemStatus.DOWNLOADED: {ItemStatus.PROCESSING, ItemStatus.FAILED},
    ItemStatus.PROCESSING: {
        ItemStatus.COMPLETED,
        ItemStatus.NEEDS_REVIEW,
        ItemStatus.RETRY_WAIT,
        ItemStatus.FAILED,
    },
    ItemStatus.RETRY_WAIT: {ItemStatus.QUEUED, ItemStatus.LEASED, ItemStatus.CANCELLED},
    ItemStatus.NEEDS_REVIEW: {ItemStatus.COMPLETED, ItemStatus.CANCELLED},
    ItemStatus.COMPLETED: set(),
    ItemStatus.DUPLICATE: set(),
    ItemStatus.BLOCKED: set(),
    ItemStatus.FAILED: set(),
    ItemStatus.SKIPPED: set(),
    ItemStatus.CANCELLED: set(),
}


class InvalidStateTransitionError(Exception):
    pass


def validate_status_transition(current: ItemStatus | str, target: ItemStatus | str) -> None:
    curr_enum = ItemStatus(current)
    targ_enum = ItemStatus(target)
    if targ_enum not in VALID_STATUS_TRANSITIONS[curr_enum]:
        raise InvalidStateTransitionError(f"Invalid state transition from {curr_enum.value} to {targ_enum.value}")


@dataclass(frozen=True)
class DiscoveredDocument:
    source_id: str
    canonical_key: str
    document_id: str
    family: str
    document_type: str
    title: str | None
    publication_date: date | None
    document_url: str
    discovery_page_url: str
    section: str | None = None
    priority: int = 100
    selection_reasons: tuple[str, ...] = ()


@dataclass
class HarvestItem:
    id: int | None
    queue_id: str
    source_id: str
    adapter_name: str
    canonical_key: str
    normalized_url: str
    original_url: str
    document_id: str
    family: str
    document_type: str
    title: str | None
    publication_date: str | None
    discovery_page_url: str
    selection_reasons_json: str
    priority: int
    status: str
    attempts: int
    next_retry_at: str | None
    lease_owner: str | None
    lease_started_at: str | None
    lease_expires_at: str | None
    artifact_id: str | None
    version_id: str | None
    raw_bytes: int
    detected_content_type: str | None
    last_error_code: str | None
    last_error_message: str | None
    discovered_at: str
    downloaded_at: str | None
    pipeline_completed_at: str | None
    completed_at: str | None
    updated_at: str


@dataclass(frozen=True)
class SelectionDecision:
    accepted: bool
    priority: int = 100
    reasons: tuple[str, ...] = ()
    rejection_code: str | None = None


@dataclass(frozen=True)
class CollectResult:
    artifact_id: str
    document_id: str
    byte_size: int
    duplicate: bool


@dataclass(frozen=True)
class PipelineResult:
    artifact_id: str
    version_id: str | None
    status: str
    record_count: int | None = None
    issue_counts: dict[str, int] | None = None
