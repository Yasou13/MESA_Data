from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiscoveredItem(BaseModel):
    """
    Represents an item discovered from a source, waiting to be fetched.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    family: str
    document_type: str
    jurisdiction: str
    title: str | None = None
    stable_key: str
    source_url: str
    fetch_method: str = "GET"
    metadata: dict[str, Any] = {}


class FetchedArtifact(BaseModel):
    """
    Represents an artifact that has been fetched and stored securely in raw storage.
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    document_id: str | None
    source_id: str
    source_url: str
    retrieved_at: str
    fetch_method: str
    http_status: int | None
    declared_content_type: str | None
    detected_content_type: str
    byte_size: int
    sha256: str
    raw_path: str
    etag: str | None = None
    last_modified: str | None = None
    error_code: str | None = None
    transport_status: str | int | None = None
    is_duplicate: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceAdapter(ABC):
    """
    Base class for source adapters that discover and fetch documents.
    """

    def __init__(self, source_id: str, config: dict[str, Any]):
        self.source_id = source_id
        self.config = config

    @abstractmethod
    def discover(self) -> Generator[DiscoveredItem, None, None]:
        """
        Discovers items from the source.
        """
