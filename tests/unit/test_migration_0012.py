import sqlite3
from pathlib import Path

import pytest

from mesa_legal_data.catalog import hash_file, insert_record, migrate


def _seed_base_hierarchy(conn: sqlite3.Connection) -> None:
    """Helper to seed minimal valid sources, documents, artifacts, and versions."""
    conn.execute(
        """INSERT INTO sources (source_id, name, authority, base_url, access_mode, enabled, policy_version, config_json, created_at, updated_at)
           VALUES ('src_test', 'Source Test', 'Authority', 'https://example.com', 'manual', 1, '1.0', '{}', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO documents (document_id, family, document_type, stable_key, lifecycle_status, created_at, updated_at)
           VALUES ('doc_test', 'legislation', 'law', 'law_test', 'active', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art_1', 'doc_test', 'src_test', 'https://example.com/1', '2026-01-01T00:00:00Z', 'manual', 'text/html', 100, 'sha256_art_1', 'raw/1.html', 'ok', '{}')"""
    )
    conn.execute(
        """INSERT INTO artifacts (artifact_id, document_id, source_id, source_url, retrieved_at, fetch_method, detected_content_type, byte_size, sha256, raw_path, transport_status, metadata_json)
           VALUES ('art_2', 'doc_test', 'src_test', 'https://example.com/2', '2026-02-01T00:00:00Z', 'manual', 'text/html', 100, 'sha256_art_2', 'raw/2.html', 'ok', '{}')"""
    )
    conn.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at, revision_number)
           VALUES ('v1', 'doc_test', 'art_1', 'consolidated_snapshot', 'canonical/v1.jsonl', 1, 'sha256_can_1', 'law_parser', '1.0', '1.0', 'passed', 'clean', 'approved', '2026-01-01T00:00:00Z', 1)"""
    )
    conn.execute(
        """INSERT INTO versions (version_id, document_id, artifact_id, version_kind, canonical_path, canonical_line, canonical_sha256, parser_name, parser_version, schema_version, validation_status, privacy_status, approval_status, created_at, revision_number)
           VALUES ('v2', 'doc_test', 'art_2', 'consolidated_snapshot', 'canonical/v2.jsonl', 1, 'sha256_can_2', 'law_parser', '1.0', '1.0', 'passed', 'clean', 'approved', '2026-02-01T00:00:00Z', 2)"""
    )


def test_migration_0012_test_a_fresh_db_table_info(tmp_path):
    """Test A — Fresh DB: Empty DB migrated 0001 -> 0012 has record_instance_id NOT NULL."""
    db_file = tmp_path / "fresh_0012.sqlite"
    migrate(None, db_file)

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    # Inspect records schema via PRAGMA table_info
    cur.execute("PRAGMA table_info(records)")
    columns = {r[1]: {"type": r[2], "notnull": r[3], "pk": r[5]} for r in cur.fetchall()}

    assert "record_instance_id" in columns
    assert columns["record_instance_id"]["type"] == "TEXT"
    assert columns["record_instance_id"]["notnull"] == 1, "record_instance_id must be NOT NULL (notnull=1)"
    assert columns["record_instance_id"]["pk"] == 1, "record_instance_id must be primary key (pk=1)"

    # Check PRAGMA pragmas
    cur.execute("PRAGMA foreign_key_check")
    assert cur.fetchall() == []

    cur.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"
    conn.close()


def test_migration_0012_test_b_null_insert_rejected(tmp_path):
    """Test B — NULL insert rejected: INSERT INTO records with record_instance_id=NULL raises IntegrityError."""
    db_file = tmp_path / "null_rejected.sqlite"
    migrate(None, db_file)

    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON")
    _seed_base_hierarchy(conn)

    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL constraint failed: records.record_instance_id"):
        conn.execute(
            """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
               VALUES (NULL, 'doc_test:art:1', 'v1', 'article', 'canonical/v1.jsonl', 1, 'sha_rec_1', 'passed', 'approved', '2026-01-01T00:00:00Z')"""
        )
    conn.close()


def test_migration_0012_test_c_normal_insert_works(tmp_path):
    """Test C — Normal insert works: Normal application-generated record_instance_id succeeds."""
    db_file = tmp_path / "normal_insert.sqlite"
    migrate(None, db_file)

    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON")
    _seed_base_hierarchy(conn)

    # 1. Direct SQL insert
    conn.execute(
        """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('v1:doc_test:art:1', 'doc_test:art:1', 'v1', 'article', 'canonical/v1.jsonl', 1, 'sha_rec_1', 'passed', 'approved', '2026-01-01T00:00:00Z')"""
    )
    conn.commit()

    # 2. insert_record catalog API
    insert_record(
        conn=conn,
        record_id="doc_test:art:2",
        version_id="v1",
        record_type="article",
        canonical_path="canonical/v1.jsonl",
        canonical_line=2,
        record_sha256="sha_rec_2",
        validation_status="passed",
        approval_status="approved",
    )

    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM records")
    assert cur.fetchone()[0] == 2

    cur.execute("SELECT record_instance_id, record_id FROM records ORDER BY canonical_line ASC")
    rows = cur.fetchall()
    assert rows == [
        ("v1:doc_test:art:1", "doc_test:art:1"),
        ("v1:doc_test:art:2", "doc_test:art:2"),
    ]
    conn.close()


def test_migration_0012_test_d_upgrade_populated_db(tmp_path):
    """Test D — Upgrade populated DB: Seeded 0011-level DB upgraded to 0012 preserves all rows, IDs, hashes, and invariants."""
    db_file = tmp_path / "upgrade_populated.sqlite"

    # 1. Set up pre-0012 DB (0001 -> 0011)
    conn_pre = sqlite3.connect(db_file)
    conn_pre.execute(
        """CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL, file_hash TEXT NOT NULL)"""
    )
    migrations_dir = Path("migrations")
    for mig_file in sorted(migrations_dir.glob("*.sql")):
        if "0012" in mig_file.name:
            continue
        sql = mig_file.read_text(encoding="utf-8")
        conn_pre.executescript(sql)
        f_hash = hash_file(mig_file)
        conn_pre.execute(
            "INSERT INTO schema_migrations (version, applied_at, file_hash) VALUES (?, '2026-01-01', ?)",
            (mig_file.name, f_hash),
        )
        conn_pre.commit()

    # Populate realistic records, releases, release_items, reviews, and validation issues
    _seed_base_hierarchy(conn_pre)

    records_data = [
        (
            "v1:doc_test:art:1",
            "doc_test:art:1",
            "v1",
            "article",
            "c1.jsonl",
            1,
            "sha_art_1",
            "passed",
            "approved",
            "2026-01-01T00:00:00Z",
        ),
        (
            "v1:doc_test:art:2",
            "doc_test:art:2",
            "v1",
            "article",
            "c1.jsonl",
            2,
            "sha_art_2",
            "passed",
            "approved",
            "2026-01-01T00:00:00Z",
        ),
        (
            "v2:doc_test:art:1",
            "doc_test:art:1",
            "v2",
            "article",
            "c2.jsonl",
            1,
            "sha_art_1_v2",
            "passed",
            "approved",
            "2026-02-01T00:00:00Z",
        ),
    ]
    for r in records_data:
        conn_pre.execute(
            """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            r,
        )

    conn_pre.execute(
        """INSERT INTO releases (release_id, release_path, status, schema_version, created_at, manifest_sha256, counts_json, source_snapshot_json)
           VALUES ('rel_1', 'releases/rel_1', 'verified', '1.0.0', '2026-01-01T00:00:00Z', 'man_sha', '{}', '[]')"""
    )
    conn_pre.execute(
        """INSERT INTO release_items (release_id, record_id, record_sha256, version_id)
           VALUES ('rel_1', 'doc_test:art:1', 'sha_art_1', 'v1')"""
    )
    conn_pre.execute(
        """INSERT INTO record_reviews (review_id, record_instance_id, version_id, record_id, record_sha256, decision, reviewer, note, reviewed_at)
           VALUES ('rev_1', 'v1:doc_test:art:1', 'v1', 'doc_test:art:1', 'sha_art_1', 'approved', 'auditor', 'ok', '2026-01-01T00:00:00Z')"""
    )
    conn_pre.commit()
    conn_pre.close()

    # 2. Run migration to apply 0012
    migrate(None, db_file)

    # 3. Verify upgraded state
    conn_post = sqlite3.connect(db_file)
    cur = conn_post.cursor()

    cur.execute("PRAGMA foreign_key_check")
    assert cur.fetchall() == []

    cur.execute("PRAGMA integrity_check")
    assert cur.fetchone()[0] == "ok"

    # Verify table schema has NOT NULL
    cur.execute("PRAGMA table_info(records)")
    columns = {r[1]: {"notnull": r[3], "pk": r[5]} for r in cur.fetchall()}
    assert columns["record_instance_id"]["notnull"] == 1
    assert columns["record_instance_id"]["pk"] == 1

    # Verify row counts and exact data preservation
    cur.execute("SELECT count(*) FROM records")
    assert cur.fetchone()[0] == 3

    cur.execute(
        "SELECT record_instance_id, record_id, version_id, record_sha256, approval_status FROM records ORDER BY record_instance_id ASC"
    )
    rows = cur.fetchall()
    assert rows == [
        ("v1:doc_test:art:1", "doc_test:art:1", "v1", "sha_art_1", "approved"),
        ("v1:doc_test:art:2", "doc_test:art:2", "v1", "sha_art_2", "approved"),
        ("v2:doc_test:art:1", "doc_test:art:1", "v2", "sha_art_1_v2", "approved"),
    ]

    # Verify dependent trigger release_items_identity_valid_insert still functions
    with pytest.raises(sqlite3.IntegrityError, match="release item version identity is invalid"):
        conn_post.execute(
            """INSERT INTO release_items (release_id, record_id, record_sha256, version_id)
               VALUES ('rel_1', 'nonexistent_rec', 'invalid_sha', 'v1')"""
        )

    conn_post.close()


def test_migration_0012_test_e_legacy_null_backfill(tmp_path):
    """Test E — Legacy NULL backfill: Pre-0012 record with NULL record_instance_id is deterministically backfilled."""
    db_file = tmp_path / "legacy_null_backfill.sqlite"

    conn_pre = sqlite3.connect(db_file)
    conn_pre.execute(
        """CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL, file_hash TEXT NOT NULL)"""
    )
    migrations_dir = Path("migrations")
    for mig_file in sorted(migrations_dir.glob("*.sql")):
        if "0012" in mig_file.name:
            continue
        sql = mig_file.read_text(encoding="utf-8")
        conn_pre.executescript(sql)
        f_hash = hash_file(mig_file)
        conn_pre.execute(
            "INSERT INTO schema_migrations (version, applied_at, file_hash) VALUES (?, '2026-01-01', ?)",
            (mig_file.name, f_hash),
        )
        conn_pre.commit()

    _seed_base_hierarchy(conn_pre)

    # Insert pre-0012 record where record_instance_id IS NULL
    conn_pre.execute(
        """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES (NULL, 'doc_test:art:9', 'v1', 'article', 'c1.jsonl', 9, 'sha_art_9', 'passed', 'approved', '2026-01-01T00:00:00Z')"""
    )
    conn_pre.commit()
    conn_pre.close()

    # Apply 0012
    migrate(None, db_file)

    conn_post = sqlite3.connect(db_file)
    cur = conn_post.cursor()

    cur.execute("SELECT record_instance_id, record_id, version_id FROM records WHERE record_id = 'doc_test:art:9'")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "v1:doc_test:art:9", (
        "Backfilled record_instance_id must match authoritative generator (version_id:record_id)"
    )
    assert row[0] is not None

    cur.execute("SELECT count(*) FROM records WHERE record_instance_id IS NULL")
    assert cur.fetchone()[0] == 0

    conn_post.close()


def test_migration_0012_test_f_version_aware_invariant(tmp_path):
    """Test F — Version-aware invariant: v1 Article 9 and v2 Article 9 maintain separate record_instance_ids and composite uniqueness."""
    db_file = tmp_path / "version_aware.sqlite"
    migrate(None, db_file)

    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON")
    _seed_base_hierarchy(conn)

    # Insert v1 Article 9
    conn.execute(
        """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('v1:doc_test:art:9', 'doc_test:art:9', 'v1', 'article', 'c1.jsonl', 9, 'sha_v1_9', 'passed', 'approved', '2026-01-01T00:00:00Z')"""
    )

    # Insert v2 Article 9 (same logical record_id, different version_id and record_instance_id)
    conn.execute(
        """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
           VALUES ('v2:doc_test:art:9', 'doc_test:art:9', 'v2', 'article', 'c2.jsonl', 9, 'sha_v2_9', 'passed', 'approved', '2026-02-01T00:00:00Z')"""
    )
    conn.commit()

    cur = conn.cursor()
    cur.execute(
        "SELECT record_instance_id, version_id, record_id FROM records WHERE record_id = 'doc_test:art:9' ORDER BY version_id ASC"
    )
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0] == ("v1:doc_test:art:9", "v1", "doc_test:art:9")
    assert rows[1] == ("v2:doc_test:art:9", "v2", "doc_test:art:9")

    # Verify duplicate (version_id, record_id) is rejected by unique constraint
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        conn.execute(
            """INSERT INTO records (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
               VALUES ('v1:doc_test:art:9:dup', 'doc_test:art:9', 'v1', 'article', 'c1.jsonl', 9, 'sha_v1_9_dup', 'passed', 'approved', '2026-01-01T00:00:00Z')"""
        )

    conn.close()
