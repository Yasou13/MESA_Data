-- Migration 0012: Enforce NOT NULL invariant on records.record_instance_id.
-- Rebuilds the records table to ensure record_instance_id is declared
-- as TEXT NOT NULL PRIMARY KEY, backfills any legacy NULL record_instance_id
-- values with deterministic version_id:record_id identities, and preserves
-- all composite uniqueness, foreign keys, and indexes.

PRAGMA foreign_keys = OFF;

DROP TRIGGER IF EXISTS release_items_identity_valid_insert;
DROP TRIGGER IF EXISTS release_items_identity_valid_update;

CREATE TABLE records_v3 (
    record_instance_id TEXT NOT NULL PRIMARY KEY,
    record_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    canonical_path TEXT NOT NULL,
    canonical_line INTEGER NOT NULL,
    record_sha256 TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (version_id) REFERENCES versions(version_id)
);

INSERT INTO records_v3 (
    record_instance_id,
    record_id,
    version_id,
    record_type,
    canonical_path,
    canonical_line,
    record_sha256,
    validation_status,
    approval_status,
    created_at
)
SELECT
    COALESCE(record_instance_id, version_id || ':' || record_id),
    record_id,
    version_id,
    record_type,
    canonical_path,
    canonical_line,
    record_sha256,
    validation_status,
    approval_status,
    created_at
FROM records;

DROP TABLE records;
ALTER TABLE records_v3 RENAME TO records;

CREATE UNIQUE INDEX IF NOT EXISTS idx_records_version_record ON records(version_id, record_id);
CREATE INDEX IF NOT EXISTS idx_records_record_id ON records(record_id);
CREATE INDEX IF NOT EXISTS idx_records_version_type ON records(version_id, record_type);
CREATE INDEX IF NOT EXISTS idx_records_approval_status ON records(approval_status);

CREATE TRIGGER release_items_identity_valid_insert
BEFORE INSERT ON release_items
WHEN NOT EXISTS (
    SELECT 1 FROM records r
    WHERE r.version_id = NEW.version_id
      AND r.record_id = NEW.record_id
      AND r.record_sha256 = NEW.record_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'release item version identity is invalid');
END;

CREATE TRIGGER release_items_identity_valid_update
BEFORE UPDATE OF version_id, record_id, record_sha256 ON release_items
WHEN NOT EXISTS (
    SELECT 1 FROM records r
    WHERE r.version_id = NEW.version_id
      AND r.record_id = NEW.record_id
      AND r.record_sha256 = NEW.record_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'release item version identity is invalid');
END;

PRAGMA foreign_keys = ON;
