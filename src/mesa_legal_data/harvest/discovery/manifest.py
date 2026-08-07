import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from mesa_legal_data.harvest.config import HarvestConfig
from mesa_legal_data.harvest.models import DiscoveredDocument, SelectionDecision
from mesa_legal_data.harvest.normalization import build_canonical_key
from mesa_legal_data.harvest.queue import enqueue_discovered_document
from mesa_legal_data.harvest.selection import evaluate_selection


def parse_manifest_stream(file_path: Path) -> Iterator[DiscoveredDocument]:
    if not file_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext == ".jsonl":
        with open(file_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line_str = line.strip()
                if not line_str:
                    continue
                row = json.loads(line_str)
                yield row_to_discovered_doc(row, line_no)
    else:
        # Default to CSV
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for line_no, row in enumerate(reader, 1):
                yield row_to_discovered_doc(row, line_no)


def row_to_discovered_doc(row: dict, line_no: int) -> DiscoveredDocument:
    source_id = str(row.get("source_id", "manifest")).strip()
    url = str(row.get("url", "")).strip()
    if not url:
        raise ValueError(f"Line {line_no}: missing required 'url' field")

    doc_id = str(row.get("document_id", "")).strip()
    if not doc_id:
        doc_id = f"doc-{line_no}"

    family = str(row.get("family", "legislation")).strip()
    doc_type = str(row.get("document_type", "law")).strip()
    title = row.get("title")
    if title:
        title = str(title).strip()

    pub_date_str = row.get("publication_date")
    pub_date: date | None = None
    if pub_date_str:
        try:
            pub_date = datetime.strptime(str(pub_date_str).strip(), "%Y-%m-%d").date()
        except ValueError:
            pub_date = None

    c_key = row.get("canonical_key")
    if not c_key:
        c_key = build_canonical_key(source_id, family, doc_type, pub_date.isoformat() if pub_date else None, doc_id)
    else:
        c_key = str(c_key).strip()

    prio = int(row.get("priority", 100))

    return DiscoveredDocument(
        source_id=source_id,
        canonical_key=c_key,
        document_id=doc_id,
        family=family,
        document_type=doc_type,
        title=title,
        publication_date=pub_date,
        document_url=url,
        discovery_page_url=f"file://{file_path_str_safe(row.get('manifest_path'))}",
        priority=prio,
        selection_reasons=("manifest_import",),
    )


def file_path_str_safe(val: Any) -> str:
    return str(val) if val else "manifest"


def import_manifest_file(
    file_path: Path,
    harvest_cfg: HarvestConfig,
    db_path: Path | None = None,
) -> dict[str, int]:
    """
    Streams CSV/JSONL manifest and enqueues documents into harvest queue.
    Returns stats dict: {"total": N, "inserted": N, "duplicate": N, "skipped": N}.
    """
    stats = {"total": 0, "inserted": 0, "duplicate": 0, "skipped": 0}

    for doc in parse_manifest_stream(file_path):
        stats["total"] += 1

        # Check source configuration selection rules if configured
        src_cfg = harvest_cfg.sources.get(doc.source_id)
        if src_cfg:
            decision = evaluate_selection(doc, src_cfg)
        else:
            # Default allow for manifest if source not explicitly in harvest.yaml
            decision = SelectionDecision(accepted=True, priority=doc.priority, reasons=("manifest_default",))

        if not decision.accepted:
            stats["skipped"] += 1
            enqueue_discovered_document(doc, "manifest", decision, db_path=db_path)
            continue

        item, result = enqueue_discovered_document(doc, "manifest", decision, db_path=db_path)
        if result == "inserted":
            stats["inserted"] += 1
        elif result == "duplicate":
            stats["duplicate"] += 1
        else:
            stats["skipped"] += 1

    return stats
