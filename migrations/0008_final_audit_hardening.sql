-- Migration 0008: final audit hardening for explicit MESA HTTP contracts
-- and version-aware release evidence.

ALTER TABLE mesa_target_settings ADD COLUMN contract_source TEXT NOT NULL DEFAULT 'unknown'
    CHECK (contract_source IN ('unknown', 'configured', 'live_verified'));
ALTER TABLE mesa_target_settings ADD COLUMN health_path TEXT NOT NULL DEFAULT '';
ALTER TABLE mesa_target_settings ADD COLUMN publish_path TEXT NOT NULL DEFAULT '';
ALTER TABLE mesa_target_settings ADD COLUMN mutation_status_path_template TEXT NOT NULL DEFAULT '';

-- Routes shipped before a local or live HTTP contract was available were assumptions.
-- Do not silently preserve them as if they were verified.
UPDATE mesa_target_settings
SET contract_source = 'unknown',
    health_path = '',
    publish_path = '',
    mutation_status_path_template = '';

ALTER TABLE release_items ADD COLUMN version_id TEXT;

UPDATE release_items
SET version_id = (
    SELECT r.version_id
    FROM records r
    WHERE r.record_id = release_items.record_id
      AND r.record_sha256 = release_items.record_sha256
    ORDER BY r.created_at DESC
    LIMIT 1
)
WHERE version_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_release_items_version ON release_items(release_id, version_id);
