-- Migration 0011: final MVP blocker closure.
-- Preserves ambiguous legacy reviews without guessing a legal version, enforces
-- version-aware release membership for new writes, and binds MESA deliveries to
-- the human-confirmed non-secret target/release fingerprints.

PRAGMA foreign_keys = OFF;

CREATE TABLE record_reviews_v4 (
    review_id TEXT NOT NULL PRIMARY KEY UNIQUE,
    record_instance_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reviewer TEXT NOT NULL,
    note TEXT,
    reviewed_at TEXT NOT NULL
);

INSERT INTO record_reviews_v4 (
    review_id, record_instance_id, version_id, record_id, record_sha256,
    decision, reviewer, note, reviewed_at
)
SELECT
    rr.review_id,
    CASE
        WHEN rr.reviewed_at >= COALESCE(
            (SELECT applied_at FROM schema_migrations WHERE version = '0010_mvp_master_closure.sql'),
            '9999-12-31T23:59:59Z'
        ) AND EXISTS (
            SELECT 1 FROM records r
            WHERE r.record_instance_id = rr.record_instance_id
              AND r.version_id = rr.version_id
              AND r.record_id = rr.record_id
              AND r.record_sha256 = rr.record_sha256
        ) THEN rr.record_instance_id
        WHEN (SELECT count(*) FROM records r
              WHERE r.record_id = rr.record_id AND r.record_sha256 = rr.record_sha256) = 1
        THEN (SELECT r.record_instance_id FROM records r
              WHERE r.record_id = rr.record_id AND r.record_sha256 = rr.record_sha256)
        ELSE 'legacy-ambiguous:' || rr.review_id
    END,
    CASE
        WHEN rr.reviewed_at >= COALESCE(
            (SELECT applied_at FROM schema_migrations WHERE version = '0010_mvp_master_closure.sql'),
            '9999-12-31T23:59:59Z'
        ) AND EXISTS (
            SELECT 1 FROM records r
            WHERE r.record_instance_id = rr.record_instance_id
              AND r.version_id = rr.version_id
              AND r.record_id = rr.record_id
              AND r.record_sha256 = rr.record_sha256
        ) THEN rr.version_id
        WHEN (SELECT count(*) FROM records r
              WHERE r.record_id = rr.record_id AND r.record_sha256 = rr.record_sha256) = 1
        THEN (SELECT r.version_id FROM records r
              WHERE r.record_id = rr.record_id AND r.record_sha256 = rr.record_sha256)
        ELSE 'legacy-version-unscoped'
    END,
    rr.record_id,
    rr.record_sha256,
    rr.decision,
    rr.reviewer,
    rr.note,
    rr.reviewed_at
FROM record_reviews rr;

DROP TABLE record_reviews;
ALTER TABLE record_reviews_v4 RENAME TO record_reviews;

CREATE INDEX idx_record_reviews_instance ON record_reviews(record_instance_id);
CREATE INDEX idx_record_reviews_version ON record_reviews(version_id);
CREATE INDEX idx_record_reviews_record ON record_reviews(record_id, reviewed_at);

CREATE TRIGGER release_items_version_required_insert
BEFORE INSERT ON release_items
WHEN NEW.version_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'release_items.version_id is required');
END;

CREATE TRIGGER release_items_version_required_update
BEFORE UPDATE OF version_id, record_id, record_sha256 ON release_items
WHEN NEW.version_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'release_items.version_id is required');
END;

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

ALTER TABLE mesa_deliveries ADD COLUMN target_config_sha256 TEXT;
ALTER TABLE mesa_deliveries ADD COLUMN release_manifest_sha256 TEXT;

PRAGMA foreign_keys = ON;
