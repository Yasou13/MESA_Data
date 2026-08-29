-- Migration 0007: MESA v4 Publisher target settings, delivery ledger, and mutation tracking

-- 1. MESA Target Settings (Single active target in MVP, non-secret parameters)
CREATE TABLE IF NOT EXISTS mesa_target_settings (
    target_key TEXT PRIMARY KEY DEFAULT 'default',
    base_url TEXT NOT NULL DEFAULT 'http://localhost:8000',
    tenant_id TEXT NOT NULL DEFAULT 'default',
    workspace_id TEXT NOT NULL DEFAULT 'legal',
    dataset_id TEXT NOT NULL DEFAULT 'tr_legislation',
    agent_id TEXT NOT NULL DEFAULT 'mesa_data_publisher',
    content_limit_chars INTEGER NOT NULL DEFAULT 32768,
    updated_at TEXT NOT NULL
);

-- Seed default target settings
INSERT OR IGNORE INTO mesa_target_settings (target_key, base_url, tenant_id, workspace_id, dataset_id, agent_id, content_limit_chars, updated_at)
VALUES ('default', 'http://localhost:8000', 'default', 'legal', 'tr_legislation', 'mesa_data_publisher', 32768, '2026-01-01T00:00:00Z');

-- 2. MESA Deliveries Ledger
CREATE TABLE IF NOT EXISTS mesa_deliveries (
    delivery_id TEXT PRIMARY KEY,
    release_id TEXT,
    target_key TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL
        CHECK (status IN ('PLANNED', 'SENDING', 'AWAITING_MUTATION', 'COMMITTED', 'PARTIAL', 'FAILED', 'CANCELLED')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_items INTEGER NOT NULL DEFAULT 0,
    committed_items INTEGER NOT NULL DEFAULT 0,
    failed_items INTEGER NOT NULL DEFAULT 0,
    skipped_items INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mesa_deliveries_status ON mesa_deliveries(status);
CREATE INDEX IF NOT EXISTS idx_mesa_deliveries_release ON mesa_deliveries(release_id);
CREATE INDEX IF NOT EXISTS idx_mesa_deliveries_created ON mesa_deliveries(created_at);

-- 3. MESA Delivery Items (Granular chunk mutation tracking)
CREATE TABLE IF NOT EXISTS mesa_delivery_items (
    item_id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    remote_mutation_id TEXT,
    remote_state TEXT NOT NULL
        CHECK (remote_state IN ('PLANNED', 'SENDING', 'QUEUED', 'PROCESSING', 'COMMITTED', 'FAILED', 'REJECTED', 'SKIPPED')),
    payload_json TEXT NOT NULL,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (delivery_id) REFERENCES mesa_deliveries(delivery_id)
);

CREATE INDEX IF NOT EXISTS idx_mesa_items_delivery_state ON mesa_delivery_items(delivery_id, remote_state);
CREATE INDEX IF NOT EXISTS idx_mesa_items_doc_ver_chunk ON mesa_delivery_items(document_id, version_id, chunk_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_mesa_items_idempotency ON mesa_delivery_items(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_mesa_items_remote_state ON mesa_delivery_items(remote_state);
