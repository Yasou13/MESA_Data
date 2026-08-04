# MESA Legal Data Import Contract & Specification

## 1. Overview
This document specifies the strict contract for importing release packages from `mesa-legal-data` into the MESA Staging Database.

## 2. Release Directory Structure
```text
data/releases/{release_id}/
├── release.json
├── manifest.json
├── data/
│   ├── legislation.jsonl
│   ├── articles.jsonl
│   ├── decisions.jsonl
│   └── citations.jsonl
└── schemas/
    ├── legislation.schema.json
    ├── article.schema.json
    ├── decision.schema.json
    ├── citation.schema.json
    └── release.schema.json
```

## 3. Pre-Import Verification Rules
- Release status in catalog MUST be `published` or `verified`.
- The release package MUST contain a valid `manifest.json`.
- All bundled files MUST match their SHA-256 digest in `manifest.json`.
- Every JSONL record MUST pass Draft 2020-12 JSON Schema validation.
- Folder name MUST match `release_id` in `release.json`.

## 4. MESA Staging Database Schema
```sql
CREATE TABLE IF NOT EXISTS imported_releases (
    release_id TEXT PRIMARY KEY,
    manifest_sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS staging_records (
    release_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (release_id, record_id),
    FOREIGN KEY (release_id) REFERENCES imported_releases(release_id)
);

CREATE TABLE IF NOT EXISTS active_release (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    release_id TEXT,
    activated_at TEXT
);
```

## 5. Idempotent Import Rules
- Importing the same `release_id` with identical `manifest_sha256` MUST return `status: "already_imported"` without raising errors or duplicating rows.
- Importing the same `release_id` with a different `manifest_sha256` MUST fail with an `ImportRollbackError` due to manifest collision.
- Staging DB insertions MUST execute inside a single atomic transaction. Any error causes a full `ROLLBACK`.

## 6. Rollback & Provenance Protocol
- Active release pointer is tracked in `active_release` (singleton row `singleton_id = 1`).
- `mesa-data release rollback --release-id TARGET_ID` switches the active release pointer to a previously imported target release.
- Provenance can be traced end-to-end via `mesa-data provenance RECORD_ID` back to the raw artifact SHA-256 and source URL.
