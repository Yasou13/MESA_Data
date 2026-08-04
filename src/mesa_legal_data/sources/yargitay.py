from pathlib import Path
from typing import Optional

from mesa_legal_data.models import FetchedArtifact
from mesa_legal_data.sources.manual import import_manual_file, import_manual_url
from mesa_legal_data.storage_paths import secure_slug


def import_yargitay_decision(
    file_path: Optional[Path] = None,
    url: Optional[str] = None,
    chamber: str = "3hd",
    case_year: int = 2023,
    case_seq: int = 4125,
    decision_year: int = 2024,
    decision_seq: int = 1872,
    title: Optional[str] = None,
) -> FetchedArtifact:
    """
    Imports a Yargıtay court decision file or URL into raw storage and catalog.
    """
    safe_chamber = secure_slug(chamber)
    doc_id = f"tr:case-law:yargitay:{safe_chamber}:{case_year}-{case_seq}:{decision_year}-{decision_seq}"
    source_id = "yargitay"
    family = "decision"
    doc_type = "yargitay_decision"

    if file_path:
        return import_manual_file(
            file_path=file_path,
            source_id=source_id,
            document_id=doc_id,
            family=family,
            document_type=doc_type,
            title=title or f"Yargıtay Kararı ({doc_id})",
        )
    elif url:
        return import_manual_url(
            url=url,
            source_id=source_id,
            document_id=doc_id,
            family=family,
            document_type=doc_type,
            title=title or f"Yargıtay Kararı ({doc_id})",
        )
    else:
        raise ValueError("Either file_path or url must be provided for Yargıtay import")
