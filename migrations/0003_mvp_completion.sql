-- Migration 0003: MVP Completion tables

CREATE TABLE IF NOT EXISTS record_reviews (
    review_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reviewer TEXT NOT NULL,
    note TEXT,
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(record_id)
);

CREATE INDEX IF NOT EXISTS idx_record_reviews_record
ON record_reviews(record_id, reviewed_at);

CREATE TABLE IF NOT EXISTS mesa_imports (
    release_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('importing', 'imported', 'failed', 'rolled_back')),
    target_db_path TEXT NOT NULL,
    imported_at TEXT,
    record_counts_json TEXT NOT NULL,
    error_summary TEXT,
    FOREIGN KEY (release_id) REFERENCES releases(release_id)
);
