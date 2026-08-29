-- Migration 0005: Version-aware records and Quality Gate support

PRAGMA foreign_keys = OFF;

-- 1. Upgrade versions table with revision tracking and quality gate fields
ALTER TABLE versions ADD COLUMN revision_number INTEGER DEFAULT 1;
ALTER TABLE versions ADD COLUMN supersedes_version_id TEXT;
ALTER TABLE versions ADD COLUMN quality_status TEXT;
ALTER TABLE versions ADD COLUMN quality_json TEXT;

CREATE INDEX IF NOT EXISTS idx_versions_doc_revision ON versions(document_id, revision_number);
CREATE INDEX IF NOT EXISTS idx_versions_quality_status ON versions(quality_status);

-- 2. Upgrade release_items without obsolete single-column record_id FK
CREATE TABLE IF NOT EXISTS release_items_v2 (
    release_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    PRIMARY KEY (release_id, record_id),
    FOREIGN KEY (release_id) REFERENCES releases(release_id)
);

INSERT INTO release_items_v2 (release_id, record_id, record_sha256)
SELECT release_id, record_id, record_sha256 FROM release_items;

DROP TABLE release_items;
ALTER TABLE release_items_v2 RENAME TO release_items;

-- 3. Upgrade record_reviews without obsolete single-column record_id FK
CREATE TABLE IF NOT EXISTS record_reviews_v2 (
    review_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reviewer TEXT NOT NULL,
    note TEXT,
    reviewed_at TEXT NOT NULL
);

INSERT INTO record_reviews_v2 (review_id, record_id, record_sha256, decision, reviewer, note, reviewed_at)
SELECT review_id, record_id, record_sha256, decision, reviewer, note, reviewed_at FROM record_reviews;

DROP TABLE record_reviews;
ALTER TABLE record_reviews_v2 RENAME TO record_reviews;

CREATE INDEX IF NOT EXISTS idx_record_reviews_record ON record_reviews(record_id, reviewed_at);

-- 4. Upgrade record_annotations without obsolete single-column record_id FK
CREATE TABLE IF NOT EXISTS record_annotations_v2 (
    annotation_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    annotation_type TEXT NOT NULL CHECK (annotation_type IN ('tag', 'note', 'custom_field')),
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO record_annotations_v2 (annotation_id, record_id, annotation_type, namespace, key, value_json, created_by, created_at, updated_at)
SELECT annotation_id, record_id, annotation_type, namespace, key, value_json, created_by, created_at, updated_at FROM record_annotations;

DROP TABLE record_annotations;
ALTER TABLE record_annotations_v2 RENAME TO record_annotations;

CREATE INDEX IF NOT EXISTS idx_record_annotations_record ON record_annotations(record_id);

-- 5. Upgrade record_revisions without obsolete single-column record_id FK
CREATE TABLE IF NOT EXISTS record_revisions_v2 (
    revision_id TEXT PRIMARY KEY,
    original_record_id TEXT NOT NULL,
    original_record_sha256 TEXT NOT NULL,
    revised_record_id TEXT NOT NULL,
    revised_record_sha256 TEXT NOT NULL,
    version_id TEXT NOT NULL,
    change_type TEXT NOT NULL,
    patch_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'validated', 'needs_review', 'approved', 'rejected', 'superseded'))
);

INSERT INTO record_revisions_v2 (revision_id, original_record_id, original_record_sha256, revised_record_id, revised_record_sha256, version_id, change_type, patch_json, reason, created_by, created_at, status)
SELECT revision_id, original_record_id, original_record_sha256, revised_record_id, revised_record_sha256, version_id, change_type, patch_json, reason, created_by, created_at, status FROM record_revisions;

DROP TABLE record_revisions;
ALTER TABLE record_revisions_v2 RENAME TO record_revisions;

CREATE INDEX IF NOT EXISTS idx_record_revisions_original ON record_revisions(original_record_id);

-- 6. Upgrade records table to support multi-version record instances and composite uniqueness
CREATE TABLE IF NOT EXISTS records_v2 (
    record_instance_id TEXT PRIMARY KEY,
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

INSERT INTO records_v2 (record_instance_id, record_id, version_id, record_type, canonical_path, canonical_line, record_sha256, validation_status, approval_status, created_at)
SELECT
    version_id || ':' || record_id,
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
ALTER TABLE records_v2 RENAME TO records;

CREATE UNIQUE INDEX IF NOT EXISTS idx_records_version_record ON records(version_id, record_id);
CREATE INDEX IF NOT EXISTS idx_records_record_id ON records(record_id);
CREATE INDEX IF NOT EXISTS idx_records_version_type ON records(version_id, record_type);
CREATE INDEX IF NOT EXISTS idx_records_approval_status ON records(approval_status);

PRAGMA foreign_keys = ON;
