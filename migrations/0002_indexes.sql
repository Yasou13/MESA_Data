CREATE INDEX idx_artifacts_document ON artifacts(document_id);
CREATE INDEX idx_artifacts_source_time ON artifacts(source_id, retrieved_at);
CREATE INDEX idx_versions_document ON versions(document_id, created_at);
CREATE INDEX idx_records_version_type ON records(version_id, record_type);
CREATE INDEX idx_issues_subject ON validation_issues(subject_type, subject_id);
CREATE INDEX idx_issues_open ON validation_issues(status, severity);
