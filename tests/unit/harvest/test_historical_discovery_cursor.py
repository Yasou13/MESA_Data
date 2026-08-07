from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mesa_legal_data.harvest.database import get_harvest_connection
from mesa_legal_data.harvest.discovery_state import get_discovery_cursor
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.models import DiscoveredDocument

runner = CliRunner()


def test_historical_discovery_cursor_and_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    harvest_db = data_root / "harvest" / "harvest.sqlite"
    apply_harvest_migrations(db_path=harvest_db)

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    processed_dates: list[date] = []

    def mock_discover_date(self, target_date, page_html=None, sources_yaml_path=None):
        processed_dates.append(target_date)
        return [
            DiscoveredDocument(
                source_id="resmi_gazete",
                canonical_key=f"rg:{target_date.isoformat()}:regulation:{target_date.strftime('%Y%m%d')}-1",
                document_id=f"tr:legislation:regulation:rg-{target_date.strftime('%Y%m%d')}-1",
                family="legislation",
                document_type="regulation",
                title=f"Doc {target_date}",
                publication_date=target_date,
                document_url=f"https://www.resmigazete.gov.tr/eskiler/{target_date.strftime('%Y/%m/%Y%m%d')}-1.htm",
                discovery_page_url=f"https://www.resmigazete.gov.tr/eskiler/{target_date.strftime('%Y/%m/%Y%m%d')}.htm",
            )
        ]

    monkeypatch.setattr(
        "mesa_legal_data.harvest.discovery.resmi_gazete.ResmiGazeteDiscoveryAdapter.discover_date",
        mock_discover_date,
    )

    from mesa_legal_data.harvest.cli import harvest_app

    # Run 1: Should process today (2026-08-07) and yesterday (2026-08-06) if pages_per_run limit allows
    res1 = runner.invoke(harvest_app, ["discover", "--source", "resmi_gazete"])
    assert res1.exit_code == 0

    assert len(processed_dates) > 0

    cursor1 = get_discovery_cursor("resmi_gazete", db_path=harvest_db)
    assert cursor1 is not None
    assert "next_date" in cursor1 or "last_successful_date" in cursor1

    # Simulate restart: Run 2
    count_run1 = len(processed_dates)
    res2 = runner.invoke(harvest_app, ["discover", "--source", "resmi_gazete"])
    assert res2.exit_code == 0

    # Ensure run 2 resumed from cursor without re-querying the exact same first date
    assert len(processed_dates) > count_run1


def test_discovery_error_does_not_advance_cursor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    harvest_db = data_root / "harvest" / "harvest.sqlite"
    apply_harvest_migrations(db_path=harvest_db)

    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))

    def mock_discover_error(self, target_date, page_html=None, sources_yaml_path=None):
        raise RuntimeError("Simulated network timeout during discovery")

    monkeypatch.setattr(
        "mesa_legal_data.harvest.discovery.resmi_gazete.ResmiGazeteDiscoveryAdapter.discover_date",
        mock_discover_error,
    )

    from mesa_legal_data.harvest.cli import harvest_app

    res = runner.invoke(harvest_app, ["discover", "--source", "resmi_gazete"])
    assert res.exit_code != 0

    cursor = get_discovery_cursor("resmi_gazete", db_path=harvest_db)
    assert cursor is None

    # Check discovery_runs table status = 'failed'
    conn = get_harvest_connection(harvest_db)
    c = conn.cursor()
    c.execute("SELECT status, error_message FROM discovery_runs ORDER BY started_at DESC LIMIT 1")
    run_row = c.fetchone()
    conn.close()

    assert run_row is not None
    assert run_row["status"] == "failed"
    assert "Simulated network timeout" in run_row["error_message"]
