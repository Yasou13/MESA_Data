from mesa_legal_data.catalog import (
    add_record_annotation,
    create_export_package,
    create_operation_job,
    create_record_revision,
    create_source_config_revision,
    delete_record_annotation,
    get_connection,
    get_db_path,
    get_export_package,
    get_operation_job,
    get_record_revision,
    get_source_config_revision,
    insert_artifact,
    insert_record,
    insert_version,
    list_audit_events,
    list_operation_jobs,
    list_record_annotations,
    list_source_config_revisions,
    log_audit_event,
    migrate,
    update_export_package_status,
    update_operation_job,
    update_record_revision_status,
    update_source_config_revision_status,
    upsert_document,
    upsert_source,
)


def test_migration_0004_and_admin_catalog_operations(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    conn = get_connection()

    # Create prerequisite source, document, artifact, version, and record for foreign keys
    upsert_source(conn, "mevzuat", "Mevzuat", "T.C. Cumhurbaşkanlığı", "https://www.mevzuat.gov.tr")
    upsert_document(conn, "doc-1", "legislation", "law", "TR", "Test Doc", "stable-doc-1", "fetched")
    insert_artifact(
        conn,
        "art-1",
        "doc-1",
        "mevzuat",
        "https://www.mevzuat.gov.tr/1",
        "2026-08-05T00:00:00Z",
        "manual",
        200,
        "text/html",
        "text/html",
        100,
        "sha123",
        "raw/payload.html",
        None,
        None,
        "fetched",
        None,
        "{}",
    )
    insert_version(
        conn,
        version_id="ver-1",
        document_id="doc-1",
        artifact_id="art-1",
        version_kind="full",
        snapshot_date=None,
        effective_from=None,
        effective_to=None,
        canonical_path="canonical/part1.jsonl",
        canonical_line=1,
        canonical_sha256="sha256",
        parser_name="mevzuat",
        parser_version="1.0.0",
        schema_version="1.0.0",
        validation_status="valid",
        privacy_status="clean",
        approval_status="pending",
    )
    insert_record(
        conn,
        record_id="rec-123",
        version_id="ver-1",
        record_type="article",
        canonical_path="canonical/part1.jsonl",
        canonical_line=1,
        record_sha256="abc",
    )

    # 1. Audit events
    evt_id = log_audit_event(
        conn,
        actor="operator_1",
        action="record_override",
        subject_type="record",
        subject_id="rec-123",
        reason="Manual fix of court name",
        old_sha256="abc",
        new_sha256="xyz",
        details_json='{"field": "court"}',
        request_id="req-1",
    )
    assert evt_id.startswith("evt-")
    events = list_audit_events(conn, subject_id="rec-123")
    assert len(events) == 1
    assert events[0]["actor"] == "operator_1"
    assert events[0]["reason"] == "Manual fix of court name"

    # 2. Record annotations
    ann_id = add_record_annotation(
        conn,
        record_id="rec-123",
        annotation_type="tag",
        namespace="mesa.operator",
        key="tags",
        value_json='["important"]',
        created_by="operator_1",
    )
    assert ann_id.startswith("ann-")
    anns = list_record_annotations(conn, "rec-123")
    assert len(anns) == 1
    assert anns[0]["key"] == "tags"

    delete_record_annotation(conn, ann_id)
    assert len(list_record_annotations(conn, "rec-123")) == 0

    # 3. Record revisions
    rev_id = create_record_revision(
        conn,
        original_record_id="rec-123",
        original_record_sha256="abc",
        revised_record_id="rec-123",
        revised_record_sha256="xyz",
        version_id="ver-1",
        change_type="override",
        patch_json='{"title": "Fixed"}',
        reason="Title fix",
        created_by="operator_1",
        status="draft",
    )
    assert rev_id.startswith("rev-")
    rev = get_record_revision(conn, rev_id)
    assert rev is not None
    assert rev["status"] == "draft"

    update_record_revision_status(conn, rev_id, "approved")
    rev_updated = get_record_revision(conn, rev_id)
    assert rev_updated["status"] == "approved"

    # 4. Source config revisions
    cfg_rev_id = create_source_config_revision(
        conn,
        config_sha256="cfg123",
        content_yaml="sources:\n  mevzuat:\n    enabled: true\n",
        reason="Enabled mevzuat",
        created_by="operator_1",
        status="draft",
    )
    assert cfg_rev_id.startswith("cfgrev-")
    cfg_rev = get_source_config_revision(conn, cfg_rev_id)
    assert cfg_rev["status"] == "draft"

    update_source_config_revision_status(conn, cfg_rev_id, "active")
    assert get_source_config_revision(conn, cfg_rev_id)["status"] == "active"
    assert len(list_source_config_revisions(conn)) == 1

    # 5. Operation jobs
    op_id = create_operation_job(
        conn,
        operation_type="bulk_review",
        requested_by="operator_1",
        input_json='{"version_id": "ver-1"}',
        progress_total=100,
    )
    assert op_id.startswith("op-")
    op = get_operation_job(conn, op_id)
    assert op["status"] == "queued"

    update_operation_job(conn, op_id, status="running", progress_current=50)
    op_running = get_operation_job(conn, op_id)
    assert op_running["status"] == "running"
    assert op_running["progress_current"] == 50

    jobs = list_operation_jobs(conn)
    assert len(jobs) == 1

    # 6. Export packages
    exp_id = create_export_package(
        conn,
        export_type="records_jsonl",
        relative_path="exports/rec_1.jsonl",
        sha256="hash123",
        byte_size=2048,
        record_count=10,
        filters_json="{}",
        created_by="operator_1",
        status="building",
    )
    assert exp_id.startswith("exp-")
    exp = get_export_package(conn, exp_id)
    assert exp["status"] == "building"

    update_export_package_status(conn, exp_id, "ready")
    assert get_export_package(conn, exp_id)["status"] == "ready"

    conn.close()
