from pathlib import Path

from mesa_legal_data.models import FetchedArtifact
from mesa_legal_data.sources.manual import import_manual_file, import_manual_url


def import_aym_decision(
    file_path: Path | None = None,
    url: str | None = None,
    kind: str = "bb",  # "bb" or "norm"
    application_year: int | None = None,
    application_number: int | None = None,
    decision_year: int | None = None,
    decision_number: int | None = None,
    title: str | None = None,
) -> FetchedArtifact:
    """
    Imports an Anayasa Mahkemesi (AYM) decision file or URL into raw storage and catalog.
    """
    if kind == "bb":
        if not application_year or not application_number:
            raise ValueError("Bireysel başvuru requires application_year and application_number")
        doc_id = f"tr:case-law:aym:bb:{application_year}-{application_number}"
    elif kind == "norm":
        if not application_year or not application_number or not decision_year or not decision_number:
            raise ValueError("Norm denetimi requires application/decision year and number")
        doc_id = f"tr:case-law:aym:norm:{application_year}-{application_number}:{decision_year}-{decision_number}"
    else:
        raise ValueError(f"Unknown AYM decision kind: {kind}")

    source_id = "aym"
    family = "decision"
    doc_type = "aym_decision"

    if file_path:
        return import_manual_file(
            file_path=file_path,
            source_id=source_id,
            document_id=doc_id,
            family=family,
            document_type=doc_type,
            title=title or f"AYM Kararı ({doc_id})",
        )
    elif url:
        return import_manual_url(
            url=url,
            source_id=source_id,
            document_id=doc_id,
            family=family,
            document_type=doc_type,
            title=title or f"AYM Kararı ({doc_id})",
        )
    else:
        raise ValueError("Either file_path or url must be provided for AYM import")
