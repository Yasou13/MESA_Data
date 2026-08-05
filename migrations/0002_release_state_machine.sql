CREATE TABLE IF NOT EXISTS releases_new (
    release_id TEXT PRIMARY KEY,
    release_path TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL
        CHECK (status IN ('preparing', 'registered', 'finalizing', 'verified', 'published', 'revoked', 'failed', 'orphaned', 'building')),
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    manifest_sha256 TEXT,
    counts_json TEXT NOT NULL,
    source_snapshot_json TEXT NOT NULL
);

INSERT OR IGNORE INTO releases_new SELECT release_id, release_path, status, schema_version, created_at, published_at, manifest_sha256, counts_json, source_snapshot_json FROM releases;
DROP TABLE releases;
ALTER TABLE releases_new RENAME TO releases;
