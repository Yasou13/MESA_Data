from datetime import date
from pathlib import Path

import pytest

from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.models import (
    DiscoveredDocument,
    InvalidStateTransitionError,
    SelectionDecision,
    validate_status_transition,
)
from mesa_legal_data.harvest.normalization import build_canonical_key, normalize_url
from mesa_legal_data.harvest.queue import (
    acquire_lease_batch,
    enqueue_discovered_document,
    update_item_status,
)


def test_url_normalization():
    raw_url = "HTTPS://WWW.Resmigazete.gov.tr/eskiler/2026/08/20260807-1.htm?utm_source=rss&a=2&b=1#section1"
    norm = normalize_url(raw_url)
    assert norm == "https://www.resmigazete.gov.tr/eskiler/2026/08/20260807-1.htm?a=2&b=1"


def test_canonical_key_builder():
    key = build_canonical_key("resmi_gazete", "legislation", "law", "2026-08-07", "7500")
    assert key == "resmi_gazete:2026-08-07:law:7500"


def test_state_transitions():
    validate_status_transition("discovered", "queued")
    validate_status_transition("queued", "leased")
    validate_status_transition("leased", "downloading")
    validate_status_transition("downloading", "downloaded")

    with pytest.raises(InvalidStateTransitionError):
        validate_status_transition("completed", "downloading")


def test_harvest_queue_flow(tmp_path: Path):
    db_file = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_file)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:law:7500",
        document_id="tr:legislation:law:7500",
        family="legislation",
        document_type="law",
        title="Test Law",
        publication_date=date(2026, 8, 7),
        document_url="https://resmigazete.gov.tr/test.pdf",
        discovery_page_url="https://resmigazete.gov.tr/archive",
    )
    decision = SelectionDecision(accepted=True, priority=150)

    # 1. Enqueue
    item, status_msg = enqueue_discovered_document(doc, "resmi_gazete", decision, db_path=db_file)
    assert status_msg == "inserted"
    assert item is not None
    assert item.status == "queued"

    # 2. Duplicate enqueue
    item_dup, dup_status = enqueue_discovered_document(doc, "resmi_gazete", decision, db_path=db_file)
    assert dup_status == "duplicate"
    assert item_dup.id == item.id

    # 3. Lease
    leased = acquire_lease_batch("worker-1", batch_size=10, lease_seconds=100, db_path=db_file)
    assert len(leased) == 1
    assert leased[0].id == item.id
    assert leased[0].status == "leased"

    # 4. Status update through pipeline
    item_dl = update_item_status(item.id, "downloading", db_path=db_file)
    assert item_dl.status == "downloading"

    item_dled = update_item_status(item.id, "downloaded", raw_bytes=1024, db_path=db_file)
    assert item_dled.status == "downloaded"

    item_proc = update_item_status(item.id, "processing", db_path=db_file)
    assert item_proc.status == "processing"

    item_comp = update_item_status(item.id, "completed", artifact_id="sha256:abc", db_path=db_file)
    assert item_comp.status == "completed"
