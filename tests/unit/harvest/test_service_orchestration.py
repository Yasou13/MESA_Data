from pathlib import Path
from unittest.mock import MagicMock, patch

from mesa_legal_data.harvest.config import load_harvest_config
from mesa_legal_data.harvest.database import get_harvest_db_path
from mesa_legal_data.harvest.migrations import apply_harvest_migrations
from mesa_legal_data.harvest.models import DiscoveredDocument
from mesa_legal_data.harvest.service import run_collection_until_pause, run_discovery_once


def test_discovery_once_mocked(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    db_path = get_harvest_db_path(custom_data_root=data_root)
    apply_harvest_migrations(db_path)

    cfg = load_harvest_config()

    with patch("mesa_legal_data.harvest.service.ResmiGazeteDiscoveryAdapter") as mock_adapter_cls:
        mock_adapter = MagicMock()
        mock_adapter.name = "resmi_gazete"
        mock_adapter.discover_date.return_value = [
            DiscoveredDocument(
                source_id="resmi_gazete",
                canonical_key="tr:legislation:law:1234",
                document_id="tr:legislation:law:1234",
                family="legislation",
                document_type="law",
                title="Test Kanun",
                publication_date=None,
                document_url="https://www.resmigazete.gov.tr/eskiler/2026/08/20260801-1.htm",
                discovery_page_url="https://www.resmigazete.gov.tr/eskiler/2026/08/20260801.htm",
            )
        ]
        mock_adapter_cls.return_value = mock_adapter

        res = run_discovery_once(source_id="resmi_gazete", harvest_cfg=cfg, db_path=db_path)
        assert res["status"] == "succeeded"
        assert res["pages_visited"] > 0
        assert res["links_seen"] > 0
        assert res["inserted"] > 0
        assert res["mode"] in ("backfill", "incremental")


def test_collection_cancellation(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    db_path = get_harvest_db_path(custom_data_root=data_root)
    apply_harvest_migrations(db_path)

    cfg = load_harvest_config()

    cancelled = True

    def is_cancelled():
        return cancelled

    res = run_collection_until_pause(
        source_id="resmi_gazete",
        harvest_cfg=cfg,
        db_path=db_path,
        is_cancelled_cb=is_cancelled,
    )
    assert res["status"] == "cancelled"
    assert res["stopped_reason"] == "USER_CANCELLED"


def test_collection_up_to_date(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    db_path = get_harvest_db_path(custom_data_root=data_root)
    apply_harvest_migrations(db_path)

    cfg = load_harvest_config()

    with patch("mesa_legal_data.harvest.service.run_discovery_once") as mock_disc:
        mock_disc.return_value = {
            "status": "succeeded",
            "source_id": "resmi_gazete",
            "mode": "incremental",
            "pages_visited": 0,
            "links_seen": 0,
            "inserted": 0,
            "duplicates": 0,
            "skipped": 0,
            "cursor": {},
        }
        with patch("mesa_legal_data.harvest.service.run_harvest_batch") as mock_batch:
            mock_batch.return_value = {
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "retry_wait": 0,
                "duplicate": 0,
                "stopped_reason": "NO_QUEUED_ITEMS",
            }
            res = run_collection_until_pause(
                source_id="resmi_gazete",
                harvest_cfg=cfg,
                db_path=db_path,
            )
            assert res["status"] == "up_to_date"


def test_collection_safety_pause_low_disk(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(data_root))
    db_path = get_harvest_db_path(custom_data_root=data_root)
    apply_harvest_migrations(db_path)

    cfg = load_harvest_config()

    with patch("mesa_legal_data.harvest.service.run_discovery_once") as mock_disc:
        mock_disc.return_value = {
            "status": "succeeded",
            "source_id": "resmi_gazete",
            "mode": "backfill",
            "pages_visited": 1,
            "links_seen": 1,
            "inserted": 1,
            "duplicates": 0,
            "skipped": 0,
            "cursor": {},
        }
        with patch("mesa_legal_data.harvest.service.run_harvest_batch") as mock_batch:
            mock_batch.return_value = {
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "retry_wait": 0,
                "duplicate": 0,
                "stopped_reason": "LOW_DISK_SPACE (free: 1000 < min: 5000)",
            }
            res = run_collection_until_pause(
                source_id="resmi_gazete",
                harvest_cfg=cfg,
                db_path=db_path,
            )
            assert res["status"] == "paused_disk_limit"
