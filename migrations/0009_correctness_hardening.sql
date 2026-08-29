-- Preserve state truth: a local polling timeout is pending, not failure.
PRAGMA foreign_keys = OFF;

CREATE TABLE mesa_delivery_items_v2 (
    item_id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    remote_mutation_id TEXT,
    remote_state TEXT NOT NULL CHECK (remote_state IN ('PLANNED', 'SENDING', 'QUEUED', 'PROCESSING', 'AWAITING_MUTATION', 'COMMITTED', 'FAILED', 'REJECTED', 'SKIPPED')),
    payload_json TEXT NOT NULL,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (delivery_id) REFERENCES mesa_deliveries(delivery_id)
);
INSERT INTO mesa_delivery_items_v2 SELECT * FROM mesa_delivery_items;
DROP TABLE mesa_delivery_items;
ALTER TABLE mesa_delivery_items_v2 RENAME TO mesa_delivery_items;
CREATE INDEX idx_mesa_items_delivery_state ON mesa_delivery_items(delivery_id, remote_state);
CREATE INDEX idx_mesa_items_doc_ver_chunk ON mesa_delivery_items(document_id, version_id, chunk_id, content_hash);
CREATE INDEX idx_mesa_items_idempotency ON mesa_delivery_items(idempotency_key);
CREATE INDEX idx_mesa_items_remote_state ON mesa_delivery_items(remote_state);

-- Do not silently merge historical collisions: applying this migration fails
-- visibly if existing data violates the invariant.
CREATE UNIQUE INDEX idx_versions_document_revision_unique ON versions(document_id, revision_number);
PRAGMA foreign_keys = ON;
