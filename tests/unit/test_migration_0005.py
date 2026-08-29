import sqlite3
from pathlib import Path

from mesa_legal_data.catalog import get_connection, hash_file, migrate


def test_migration_0005_data_preservation_and_backfill(tmp_path):
    """
    Migration Test:
    - Sets up schema up to 0004
    - Inserts legacy data
    - Applies migration 0005
    - Verifies zero data loss, correct backfill, and multi-version record capability
    """
    db_file = tmp_path / "test_catalog.sqlite"
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Apply 0001 - 0004 manually first
    migration_files = sorted(migrations_dir.glob("000[1-4]_*.sql"))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            file_hash TEXT NOT NULL
        );
    """)

    for mf in migration_files:
        with open(mf, "r", encoding="utf-8") as f:
            sql = f.read()
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations VALUES (?, '2026-01-01T00:00:00Z', ?)",
            (mf.name, hash_file(mf)),
        )
    conn.commit()

    # Insert legacy records
    conn.execute(
        """INSERT INTO sources VALUES ('mevzuat', 'Mevzuat', 'Authority', 'https://example.com', 'manual', 1, '1.0', '{}', '2026-01-01', '2026-01-01')"""
    )
    conn.execute(
        """INSERT INTO documents VALUES ('doc-1', 'legislation', 'law', 'TR', 'Legacy Law', 'key-1', 'ver-1', 'active', '2026-01-01', '2026-01-01')"""
    )
    conn.execute(
        """INSERT INTO artifacts VALUES ('art-1', 'doc-1', 'mevzuat', 'http://ex.com', '2026-01-01', 'manual', 200, 'text/html', 'text/html', 100, 'sha1111111111111111111111111111111111111111111111111111111111111111', 'raw/1.html', NULL, NULL, 'verified', NULL, '{}')"""
    )
    conn.execute(
        """INSERT INTO versions VALUES ('ver-1', 'doc-1', 'art-1', 'consolidated_snapshot', '2026-01-01', NULL, NULL, 'canon/1.jsonl', 1, 'csha1', 'parser', '1.0', '1.0', 'valid', 'clean', 'approved', '2026-01-01')"""
    )
    conn.execute(
        """INSERT INTO records VALUES ('tr:legislation:law:1:article:1', 'ver-1', 'article', 'canon/1.jsonl', 1, 'recsha1', 'valid', 'approved', '2026-01-01')"""
    )
    conn.execute(
        """INSERT INTO record_reviews VALUES ('rev-1', 'tr:legislation:law:1:article:1', 'recsha1', 'approved', 'reviewer-1', 'LGTM', '2026-01-01')"""
    )
    conn.execute(
        """INSERT INTO releases VALUES ('rel-1', 'rel/1', 'published', '1.0', '2026-01-01', '2026-01-01', 'msha1', '{}', '{}')"""
    )
    conn.execute("""INSERT INTO release_items VALUES ('rel-1', 'tr:legislation:law:1:article:1', 'recsha1')""")
    conn.commit()
    conn.close()

    # Now apply full migrate() including 0005
    migrate(migrations_dir=migrations_dir, db_path=db_file)

    conn2 = get_connection(db_file)
    c = conn2.cursor()

    # Verify 0005 migration applied
    c.execute("SELECT version FROM schema_migrations WHERE version LIKE '0005%'")
    m0005 = c.fetchone()
    assert m0005 is not None

    # Verify versions table fields
    c.execute("SELECT version_id, revision_number, quality_status FROM versions WHERE version_id = 'ver-1'")
    v_row = c.fetchone()
    assert v_row is not None
    assert v_row[0] == "ver-1"
    assert v_row[1] == 1  # revision_number backfilled to 1

    # Verify records table upgraded and backfilled
    c.execute(
        "SELECT record_instance_id, record_id, version_id, record_sha256 FROM records WHERE record_id = 'tr:legislation:law:1:article:1'"
    )
    r_row = c.fetchone()
    assert r_row is not None
    assert r_row[0] == "ver-1:tr:legislation:law:1:article:1"
    assert r_row[1] == "tr:legislation:law:1:article:1"
    assert r_row[2] == "ver-1"
    assert r_row[3] == "recsha1"

    # Verify dependent tables preserved data
    c.execute("SELECT review_id, record_id, record_sha256 FROM record_reviews WHERE review_id = 'rev-1'")
    assert c.fetchone() == ("rev-1", "tr:legislation:law:1:article:1", "recsha1")

    c.execute("SELECT release_id, record_id, record_sha256 FROM release_items WHERE release_id = 'rel-1'")
    assert c.fetchone() == ("rel-1", "tr:legislation:law:1:article:1", "recsha1")
    c.execute("SELECT version_id FROM release_items WHERE release_id = 'rel-1'")
    assert c.fetchone() == ("ver-1",)

    c.execute(
        "SELECT contract_source, health_path, publish_path, mutation_status_path_template FROM mesa_target_settings"
    )
    assert c.fetchone() == ("unknown", "", "", "")

    # Verify inserting Version 2 for the same article does NOT collide or overwrite Version 1
    conn2.execute(
        """INSERT INTO artifacts VALUES ('art-2', 'doc-1', 'mevzuat', 'http://ex.com/2', '2026-06-01', 'manual', 200, 'text/html', 'text/html', 100, 'sha2222222222222222222222222222222222222222222222222222222222222222', 'raw/2.html', NULL, NULL, 'verified', NULL, '{}')"""
    )
    conn2.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at, revision_number, supersedes_version_id, quality_status)
           VALUES ('ver-2', 'doc-1', 'art-2', 'consolidated_snapshot', 'canon/2.jsonl', 1, 'csha2', 'parser', '1.0', '1.0', 'valid', 'clean', 'pending', '2026-06-01', 2, 'ver-1', 'PASS')"""
    )
    conn2.execute(
        """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('ver-2:tr:legislation:law:1:article:1', 'tr:legislation:law:1:article:1', 'ver-2', 'article', 'canon/2.jsonl', 1, 'recsha2_amended', 'valid', 'pending', '2026-06-01')"""
    )
    conn2.commit()

    # Check both versions of Article 1 exist side-by-side
    c.execute(
        "SELECT version_id, record_sha256, approval_status FROM records WHERE record_id = 'tr:legislation:law:1:article:1' ORDER BY created_at ASC"
    )
    all_art1 = c.fetchall()
    assert len(all_art1) == 2
    assert all_art1[0] == ("ver-1", "recsha1", "approved")
    assert all_art1[1] == ("ver-2", "recsha2_amended", "pending")

    conn2.close()
