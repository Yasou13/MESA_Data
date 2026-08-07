from pathlib import Path

from mesa_legal_data.harvest.budgets import (
    check_free_disk_space,
    check_source_error_circuit_breaker,
    get_daily_budget_usage,
    record_daily_budget,
)
from mesa_legal_data.harvest.migrations import apply_harvest_migrations


def test_harvest_budget_and_circuit_breaker_integration(tmp_path: Path):
    db_file = tmp_path / "harvest.sqlite"
    apply_harvest_migrations(db_file)

    # Record daily budget usage
    record_daily_budget("resmi_gazete", 1048576, success=True, db_path=db_file)
    usage = get_daily_budget_usage("resmi_gazete", db_path=db_file)
    assert usage["documents_downloaded"] == 1
    assert usage["raw_bytes_downloaded"] == 1048576

    # Test circuit breaker with < 10 items
    breaker = check_source_error_circuit_breaker("resmi_gazete", db_path=db_file)
    assert breaker is False


def test_free_disk_space_check(tmp_path: Path):
    # Free disk check on valid directory
    ok, free_b = check_free_disk_space(minimum_free_bytes=100, custom_data_root=tmp_path)
    assert ok is True
    assert free_b > 100
