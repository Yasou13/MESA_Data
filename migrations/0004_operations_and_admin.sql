-- Migration 0004: Operations, Revisions, Annotations, Audit, Jobs, and Export Packages

CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    old_sha256 TEXT,
    new_sha256 TEXT,
    reason TEXT,
    details_json TEXT NOT NULL,
    request_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_events_subject
ON audit_events(subject_type, subject_id, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_events_action
ON audit_events(action, created_at);

CREATE TABLE IF NOT EXISTS record_annotations (
    annotation_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    annotation_type TEXT NOT NULL
        CHECK (annotation_type IN ('tag', 'note', 'custom_field')),
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(record_id)
);

CREATE INDEX IF NOT EXISTS idx_record_annotations_record
ON record_annotations(record_id);

CREATE TABLE IF NOT EXISTS record_revisions (
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
    status TEXT NOT NULL
        CHECK (status IN ('draft', 'validated', 'needs_review', 'approved', 'rejected', 'superseded')),
    FOREIGN KEY (original_record_id) REFERENCES records(record_id),
    FOREIGN KEY (revised_record_id) REFERENCES records(record_id)
);

CREATE INDEX IF NOT EXISTS idx_record_revisions_original
ON record_revisions(original_record_id);

CREATE TABLE IF NOT EXISTS source_config_revisions (
    revision_id TEXT PRIMARY KEY,
    config_sha256 TEXT NOT NULL,
    content_yaml TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('draft', 'active', 'superseded', 'rejected')),
    validation_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_jobs (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted')),
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

CREATE INDEX IF NOT EXISTS idx_operation_jobs_status
ON operation_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS export_packages (
    export_id TEXT PRIMARY KEY,
    export_type TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    record_count INTEGER,
    filters_json TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('building', 'ready', 'failed', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_export_packages_status
ON export_packages(status, created_at);
