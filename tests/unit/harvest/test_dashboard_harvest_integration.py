from pathlib import Path

from fastapi.testclient import TestClient

from mesa_legal_data.catalog import migrate as run_catalog_migrations
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.models import DiscoveredDocument, SelectionDecision
from mesa_legal_data.harvest.queue import enqueue_discovered_document
from mesa_legal_data.harvest.reporting import get_harvest_dashboard_summary
from mesa_legal_data.web.app import create_app

app = create_app()


def test_harvest_dashboard_summary_absent_db(tmp_path: Path) -> None:
    absent_db = tmp_path / "non_existent_harvest.sqlite"
    summary = get_harvest_dashboard_summary(db_path=absent_db)
    assert summary["enabled"] is True
    assert summary["initialized"] is False


def test_harvest_dashboard_summary_populated_db(tmp_path: Path) -> None:
    db_path = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_path=db_path)

    doc = DiscoveredDocument(
        source_id="resmi_gazete",
        canonical_key="rg:2026-08-07:law:dash-1",
        document_id="doc-dash-1",
        family="legislation",
        document_type="law",
        title="Dash Law",
        publication_date=None,
        document_url="https://resmigazete.gov.tr/dash1.htm",
        discovery_page_url="https://resmigazete.gov.tr/index.htm",
    )
    enqueue_discovered_document(
        doc,
        adapter_name="resmi_gazete",
        decision=SelectionDecision(accepted=True, priority=100),
        db_path=db_path,
    )

    summary = get_harvest_dashboard_summary(db_path=db_path)
    assert summary["enabled"] is True
    assert summary["initialized"] is True
    assert summary["total_items"] == 1
    assert summary["queued"] == 1
    assert summary["source"] == "resmi_gazete"


def test_api_dashboard_stats_contains_counts_and_harvest(monkeypatch, tmp_path: Path) -> None:
    sandbox_data = tmp_path / "data_root"
    sandbox_data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(sandbox_data))
    run_catalog_migrations()

    client = TestClient(app)
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 200

    data = response.json()["data"]
    assert "counts" in data
    assert "documents" in data["counts"]
    assert "artifacts" in data["counts"]
    assert "records" in data["counts"]

    assert "harvest" in data
    assert data["harvest"]["enabled"] is True
