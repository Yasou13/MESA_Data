import sqlite3

import pytest

from mesa_legal_data.catalog import CatalogError, migrate


def test_migration_runner(tmp_path):
    db_path = tmp_path / "test.sqlite"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    # Create migration 1
    m1 = migrations_dir / "0001_test.sql"
    m1.write_text("CREATE TABLE test (id INTEGER);")

    # First migration
    migrate(migrations_dir, db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test';")
    assert cursor.fetchone() is not None

    cursor.execute("SELECT version FROM schema_migrations;")
    assert cursor.fetchone()[0] == "0001_test.sql"
    conn.close()

    # Second migration (no-op)
    migrate(migrations_dir, db_path)

    # Modify migration 1 to cause hash mismatch
    m1.write_text("CREATE TABLE test (id INTEGER, name TEXT);")
    with pytest.raises(CatalogError, match="Migration hash mismatch"):
        migrate(migrations_dir, db_path)
