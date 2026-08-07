from datetime import UTC, datetime
from pathlib import Path

from mesa_legal_data.harvest.database import get_harvest_connection

MIGRATION_V1_SQL = """
CREATE TABLE IF NOT EXISTS harvest_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS harvest_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    adapter_name TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    original_url TEXT NOT NULL,
    document_id TEXT NOT NULL,
    family TEXT NOT NULL,
    document_type TEXT NOT NULL,
    title TEXT,
    publication_date TEXT,
    discovery_page_url TEXT NOT NULL,
    selection_reasons_json TEXT NOT NULL DEFAULT '[]',
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'discovered',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    lease_owner TEXT,
    lease_started_at TEXT,
    lease_expires_at TEXT,
    artifact_id TEXT,
    version_id TEXT,
    raw_bytes INTEGER NOT NULL DEFAULT 0,
    detected_content_type TEXT,
    last_error_code TEXT,
    last_error_message TEXT,
    discovered_at TEXT NOT NULL,
    downloaded_at TEXT,
    pipeline_completed_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, canonical_key),
    UNIQUE(source_id, normalized_url)
);

CREATE INDEX IF NOT EXISTS idx_harvest_items_status_priority ON harvest_items(status, priority DESC, discovered_at ASC);
CREATE INDEX IF NOT EXISTS idx_harvest_items_lease ON harvest_items(lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_harvest_items_next_retry ON harvest_items(next_retry_at);
CREATE INDEX IF NOT EXISTS idx_harvest_items_source_status ON harvest_items(source_id, status);

CREATE TABLE IF NOT EXISTS harvest_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    stage TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    result TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    http_status INTEGER,
    bytes_received INTEGER DEFAULT 0,
    artifact_id TEXT,
    FOREIGN KEY(item_id) REFERENCES harvest_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discovery_runs (
    run_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    pages_visited INTEGER DEFAULT 0,
    links_seen INTEGER DEFAULT 0,
    items_inserted INTEGER DEFAULT 0,
    items_duplicate INTEGER DEFAULT 0,
    items_skipped INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS discovery_cursors (
    source_id TEXT PRIMARY KEY,
    cursor_data_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_budgets (
    source_id TEXT NOT NULL,
    budget_date TEXT NOT NULL,
    requests_used INTEGER DEFAULT 0,
    documents_downloaded INTEGER DEFAULT 0,
    raw_bytes_downloaded INTEGER DEFAULT 0,
    pipeline_success INTEGER DEFAULT 0,
    pipeline_failed INTEGER DEFAULT 0,
    PRIMARY KEY(source_id, budget_date)
);
"""


def apply_harvest_migrations(db_path: Path | None = None) -> None:
    conn = get_harvest_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='harvest_schema_migrations';")
        if not cursor.fetchone():
            cursor.executescript(MIGRATION_V1_SQL)
            now_iso = datetime.now(UTC).isoformat()
            cursor.execute(
                "INSERT INTO harvest_schema_migrations (version, applied_at) VALUES (1, ?)",
                (now_iso,),
            )
            conn.commit()
    finally:
        conn.close()
