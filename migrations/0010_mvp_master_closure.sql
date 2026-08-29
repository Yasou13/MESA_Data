-- Migration 0010: MVP Master Closure and Correctness Hardening
-- Adds instance-scoped reviews, version-scoped validation issues, and truthful operation states.

PRAGMA foreign_keys = OFF;

-- 1. Upgrade record_reviews to enforce non-null review_id and scope to version_id and record_instance_id
CREATE TABLE IF NOT EXISTS record_reviews_v3 (
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

INSERT INTO record_reviews_v3 (
    review_id,
    record_instance_id,
    version_id,
    record_id,
    record_sha256,
    decision,
    reviewer,
    note,
    reviewed_at
)
SELECT
    COALESCE(
        rr.review_id,
        'legacy-rev-' || hex(randomblob(4)) || '-' || abs(random())
    ) AS review_id,
    COALESCE(
        (
            SELECT r.record_instance_id
            FROM records r
            WHERE r.record_id = rr.record_id
              AND r.record_sha256 = rr.record_sha256
            ORDER BY r.created_at DESC
            LIMIT 1
        ),
        'legacy-instance:' || rr.record_id
    ) AS record_instance_id,
    COALESCE(
        (
            SELECT r.version_id
            FROM records r
            WHERE r.record_id = rr.record_id
              AND r.record_sha256 = rr.record_sha256
            ORDER BY r.created_at DESC
            LIMIT 1
        ),
        'legacy-version-unscoped'
    ) AS version_id,
    rr.record_id,
    rr.record_sha256,
    rr.decision,
    rr.reviewer,
    rr.note,
    rr.reviewed_at
FROM record_reviews rr;

DROP TABLE record_reviews;
ALTER TABLE record_reviews_v3 RENAME TO record_reviews;

CREATE INDEX IF NOT EXISTS idx_record_reviews_instance ON record_reviews(record_instance_id);
CREATE INDEX IF NOT EXISTS idx_record_reviews_version ON record_reviews(version_id);
CREATE INDEX IF NOT EXISTS idx_record_reviews_record ON record_reviews(record_id, reviewed_at);

-- 2. Upgrade validation_issues with version_id and record_instance_id columns
CREATE TABLE IF NOT EXISTS validation_issues_v2 (
    issue_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    version_id TEXT,
    record_instance_id TEXT,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error', 'blocker')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'waived', 'resolved')),
    opened_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_note TEXT
);

INSERT INTO validation_issues_v2 (
    issue_id,
    subject_type,
    subject_id,
    version_id,
    record_instance_id,
    severity,
    code,
    message,
    details_json,
    status,
    opened_at,
    resolved_at,
    resolved_by,
    resolution_note
)
SELECT
    issue_id,
    subject_type,
    subject_id,
    CASE
        WHEN subject_type = 'version' THEN subject_id
        WHEN subject_type = 'record' AND instr(subject_id, ':version:') > 0 THEN
            substr(subject_id, 1, instr(subject_id, ':article:') - 1)
        ELSE NULL
    END AS version_id,
    CASE
        WHEN subject_type = 'record' AND instr(subject_id, ':version:') > 0 THEN subject_id
        ELSE NULL
    END AS record_instance_id,
    severity,
    code,
    message,
    details_json,
    status,
    opened_at,
    resolved_at,
    resolved_by,
    resolution_note
FROM validation_issues;

DROP TABLE validation_issues;
ALTER TABLE validation_issues_v2 RENAME TO validation_issues;

CREATE INDEX IF NOT EXISTS idx_validation_issues_status_sev ON validation_issues(status, severity);
CREATE INDEX IF NOT EXISTS idx_validation_issues_version ON validation_issues(version_id, status);
CREATE INDEX IF NOT EXISTS idx_validation_issues_instance ON validation_issues(record_instance_id, status);

-- 3. Upgrade operation_jobs with truthful operation statuses: partial, awaiting_external
CREATE TABLE IF NOT EXISTS operation_jobs_v2 (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted', 'partial', 'awaiting_external')),
    requested_by TEXT NOT NULL,
    input_json TEXT NOT NULL,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER,
    result_json TEXT,
    error_summary TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

INSERT INTO operation_jobs_v2 SELECT * FROM operation_jobs;
DROP TABLE operation_jobs;
ALTER TABLE operation_jobs_v2 RENAME TO operation_jobs;

CREATE INDEX IF NOT EXISTS idx_operation_jobs_status ON operation_jobs(status, created_at);

PRAGMA foreign_keys = ON;
