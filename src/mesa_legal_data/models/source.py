from typing import Optional, Dict, Any, Generator
from pydantic import BaseModel, ConfigDict
from abc import ABC, abstractmethod


class DiscoveredItem(BaseModel):
    """
    Represents an item discovered from a source, waiting to be fetched.
    """
    model_config = ConfigDict(frozen=True)
    
    document_id: str
    family: str
    document_type: str
    jurisdiction: str
    title: Optional[str] = None
    stable_key: str
    source_url: str
    fetch_method: str = "GET"
    metadata: Dict[str, Any] = {}


class FetchedArtifact(BaseModel):
    """
    Represents an artifact that has been fetched and stored securely in raw storage.
    """
    model_config = ConfigDict(frozen=True)
    
    artifact_id: str
    document_id: Optional[str]
    source_id: str
    source_url: str
    retrieved_at: str
    fetch_method: str
    http_status: Optional[int]
    declared_content_type: Optional[str]
    detected_content_type: str
    byte_size: int
    sha256: str
    raw_path: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    transport_status: str
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = {}


class SourceAdapter(ABC):
    """
    Base class for source adapters that discover and fetch documents.
    """
    
    def __init__(self, source_id: str, config: Dict[str, Any]):
        self.source_id = source_id
        self.config = config
        
    @abstractmethod
    def discover(self) -> Generator[DiscoveredItem, None, None]:
        """
        Discovers items from the source.
        """
        pass
