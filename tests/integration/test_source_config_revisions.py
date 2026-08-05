import hashlib

from mesa_legal_data.catalog import (
    activate_source_config_revision,
    create_source_config_revision,
    get_connection,
    get_db_path,
    get_source_config_revision,
    list_source_config_revisions,
    migrate,
)


def test_source_config_revisions_activation(tmp_path, monkeypatch):
    monkeypatch.setenv("MESA_DATA_DATA_ROOT", str(tmp_path))
    db_path = get_db_path()
    migrate(None, db_path)

    conn = get_connection()
    yaml1 = "sources:\n  mevzuat:\n    enabled: true\n    policy_version: v1\n"
    h1 = hashlib.sha256(yaml1.encode("utf-8")).hexdigest()

    # 1. Create draft config revision
    rev_id1 = create_source_config_revision(
        conn,
        config_sha256=h1,
        content_yaml=yaml1,
        reason="Initial policy config",
        created_by="admin",
    )
    assert rev_id1.startswith("cfgrev-")

    revs = list_source_config_revisions(conn)
    assert len(revs) >= 1

    # 2. Activate config revision
    act_res = activate_source_config_revision(conn, rev_id1, actor="admin_user")
    assert act_res["status"] == "active"

    # 3. Create and activate a second revision -> first set to superseded
    yaml2 = "sources:\n  mevzuat:\n    enabled: true\n    policy_version: v2\n"
    h2 = hashlib.sha256(yaml2.encode("utf-8")).hexdigest()
    rev_id2 = create_source_config_revision(
        conn,
        config_sha256=h2,
        content_yaml=yaml2,
        reason="Updated to policy v2",
        created_by="admin",
    )

    act_res2 = activate_source_config_revision(conn, rev_id2, actor="admin_user")
    assert act_res2["status"] == "active"

    rev1_after = get_source_config_revision(conn, rev_id1)
    assert rev1_after["status"] == "superseded"

    conn.close()
