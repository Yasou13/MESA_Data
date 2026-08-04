
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    authority TEXT NOT NULL,
    base_url TEXT NOT NULL,
    access_mode TEXT NOT NULL
        CHECK (access_mode IN ('manual', 'approved_web', 'licensed_api')),
    enabled INTEGER NOT NULL DEFAULT 0,
    policy_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    family TEXT NOT NULL
        CHECK (family IN ('legislation', 'decision')),
    document_type TEXT NOT NULL,
    jurisdiction TEXT NOT NULL DEFAULT 'TR',
    title TEXT,
    stable_key TEXT NOT NULL UNIQUE,
    current_version_id TEXT,
    lifecycle_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    document_id TEXT,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    fetch_method TEXT NOT NULL,
    http_status INTEGER,
    declared_content_type TEXT,
    detected_content_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL UNIQUE,
    raw_path TEXT NOT NULL UNIQUE,
    etag TEXT,
    last_modified TEXT,
    transport_status TEXT NOT NULL,
    error_code TEXT,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(document_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE versions (
    version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    version_kind TEXT NOT NULL,
    snapshot_date TEXT,
    effective_from TEXT,
    effective_to TEXT,
    canonical_path TEXT NOT NULL,
    canonical_line INTEGER NOT NULL,
    canonical_sha256 TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    privacy_status TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(document_id),
    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id)
);

CREATE TABLE records (
    record_id TEXT PRIMARY KEY,
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

CREATE TABLE processing_runs (
    run_id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    source_id TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    code_version TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    input_json TEXT NOT NULL,
    counters_json TEXT NOT NULL,
    error_summary TEXT
);

CREATE TABLE validation_issues (
    issue_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    severity TEXT NOT NULL
        CHECK (severity IN ('info', 'warning', 'error', 'blocker')),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('open', 'waived', 'resolved')),
    opened_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution_note TEXT
);

CREATE TABLE releases (
    release_id TEXT PRIMARY KEY,
    release_path TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL
        CHECK (status IN ('building', 'verified', 'published', 'revoked')),
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    manifest_sha256 TEXT,
    counts_json TEXT NOT NULL,
    source_snapshot_json TEXT NOT NULL
);

CREATE TABLE release_items (
    release_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    PRIMARY KEY (release_id, record_id),
    FOREIGN KEY (release_id) REFERENCES releases(release_id),
    FOREIGN KEY (record_id) REFERENCES records(record_id)
);
