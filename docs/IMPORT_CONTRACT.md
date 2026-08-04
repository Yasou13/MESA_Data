# MESA Data Import Contract & Rules

## 1. Overview
This document specifies the strict contract for importing release packages from `mesa-legal-data` into MESA.

## 2. Pre-Import Requirements
- Release package MUST contain a valid `manifest.json`.
- All bundled file SHA-256 hashes MUST match `manifest.json`.
- Release status in catalog MUST be `published`.

## 3. Idempotent Import Rules
- Importing the same `release_id` multiple times MUST NOT create duplicate records.
- Records are upserted using immutable record IDs and content SHA-256 signatures.

## 4. Rollback Protocol
- If an import fails midway, the transaction is rolled back.
- Previous published release status remains active.
