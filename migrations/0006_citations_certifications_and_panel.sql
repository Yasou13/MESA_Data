-- Migration 0006: Citations semantics, parser certifications, operational source settings, and audit sampling

-- 1. Parser certifications table
CREATE TABLE IF NOT EXISTS parser_certifications (
    source_id TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    certified INTEGER NOT NULL DEFAULT 0,
    certified_at TEXT,
    certified_by TEXT,
    PRIMARY KEY (source_id, parser_name, parser_version)
);

-- 2. Operational source settings table
CREATE TABLE IF NOT EXISTS source_operational_settings (
    source_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    auto_approval_enabled INTEGER NOT NULL DEFAULT 0,
    weekly_sample_count INTEGER NOT NULL DEFAULT 10,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);

-- 3. Version audit sampling and auto approval tracking
ALTER TABLE versions ADD COLUMN is_audit_sample INTEGER DEFAULT 0;
ALTER TABLE versions ADD COLUMN audit_sample_reason TEXT;
ALTER TABLE versions ADD COLUMN auto_approved INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_versions_audit_sample ON versions(is_audit_sample);
CREATE INDEX IF NOT EXISTS idx_versions_auto_approved ON versions(auto_approved);

-- 4. Initial seed for certified parsers for built-in sources
INSERT OR IGNORE INTO parser_certifications (source_id, parser_name, parser_version, certified, certified_at, certified_by)
VALUES
    ('mevzuat', 'legislation_parser', '1.0.0', 1, '2026-01-01T00:00:00Z', 'system'),
    ('resmi_gazete', 'legislation_parser', '1.0.0', 1, '2026-01-01T00:00:00Z', 'system'),
    ('yargitay', 'decision_parser', '1.0.0', 1, '2026-01-01T00:00:00Z', 'system'),
    ('danistay', 'decision_parser', '1.0.0', 1, '2026-01-01T00:00:00Z', 'system'),
    ('anayasa_mahkemesi', 'decision_parser', '1.0.0', 1, '2026-01-01T00:00:00Z', 'system');
