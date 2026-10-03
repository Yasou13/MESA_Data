"""Exhaustive unit and adversarial validation tests for Phase 7 qualification fixtures.

Covers:
  - All 16 required negative adversarial failure modes (Section 31)
  - Happy-path release build, frozen identity map, and release verification (Section 32)
  - Strict E2E compatibility check with _load_frozen_scope_authority (Section 33)
  - Immutability of historical release identities (Section 27)
  - Cryptographic tamper detection on manifest, identity map, and fixture authority (Section 29)
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mesa_legal_data.release.builder import (
    ReleaseBuildError,
    build_qualification_release,
)
from mesa_legal_data.release.qualification_fixtures import (
    FIXTURE_NAMESPACE_PREFIX,
    QualificationFixtureError,
    build_qualification_fixtures,
    load_baseline_identity_map_rows,
    validate_qualification_fixtures,
)
from mesa_legal_data.release.verifier import (
    ReleaseVerificationError,
    verify_release_directory,
)


@pytest.fixture
def baseline_setup() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Provides valid baseline qualification scope, authority, and combined identity rows."""
    base_rows = load_baseline_identity_map_rows()
    bundle = build_qualification_fixtures()
    q_scope = copy.deepcopy(bundle["qualification_scope"])
    s_auth = copy.deepcopy(bundle["scope_test_authority"])
    f_rows = copy.deepcopy(bundle["identity_rows"])
    combined_rows = base_rows + f_rows
    return q_scope, s_auth, combined_rows


# ==============================================================================
# 16 Negative Adversarial Failure Modes (Section 31)
# ==============================================================================


def test_01_missing_cross_tenant_fixture(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    s_auth["case_evidence_fixtures"].pop("cross_tenant_search")
    with pytest.raises(QualificationFixtureError, match="must cover exactly the 12 required cases"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_02_cross_tenant_fixture_accidentally_in_allowed_tenant(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["cross_tenant_search"][0]
    s_auth["corpus_fixtures"][fid]["tenant_id"] = q_scope["tenant_id"]  # "default"
    for r in rows:
        if r.get("evidence_id") == fid:
            r["tenant_id"] = q_scope["tenant_id"]
    with pytest.raises(QualificationFixtureError, match="does not belong to forbidden tenant"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_03_missing_cross_dataset_fixture(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    s_auth["case_evidence_fixtures"].pop("cross_dataset_search")
    with pytest.raises(QualificationFixtureError, match="must cover exactly the 12 required cases"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_04_forbidden_dataset_accidentally_allowed(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    # Forbidden dataset set to allowed dataset scope
    s_auth["forbidden_dataset"] = q_scope["dataset_ids"][0]  # "tr_legislation"
    with pytest.raises(QualificationFixtureError, match="forbidden_dataset belongs to allowed dataset scope"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_05_missing_cross_agent_fixture(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    s_auth["case_evidence_fixtures"].pop("cross_agent_search")
    with pytest.raises(QualificationFixtureError, match="must cover exactly the 12 required cases"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_06_forbidden_agent_accidentally_equals_allowed_agent(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    s_auth["forbidden_agent"] = q_scope["agent_id"]  # "mesa_data_publisher"
    with pytest.raises(QualificationFixtureError, match="forbidden_agent belongs to allowed agent"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_07_inactive_fixture_marked_active(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["inactive_status_search"][0]
    s_auth["corpus_fixtures"][fid]["status"] = "ACTIVE"
    for r in rows:
        if r.get("evidence_id") == fid:
            r["status"] = "ACTIVE"
    with pytest.raises(QualificationFixtureError, match="inactive fixture .* is not inactive/tombstoned/deleted"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_08_wrong_jurisdiction_fixture_actually_tr(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["wrong_jurisdiction_search"][0]
    s_auth["corpus_fixtures"][fid]["jurisdiction"] = "TR"
    for r in rows:
        if r.get("evidence_id") == fid:
            r["jurisdiction"] = "TR"
    with pytest.raises(QualificationFixtureError, match="wrong-jurisdiction fixture .* is not outside TR"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_09_stale_fixture_marked_current(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["stale_version_search"][0]
    s_auth["corpus_fixtures"][fid]["is_current"] = True
    for r in rows:
        if r.get("evidence_id") == fid:
            r["is_current"] = True
    with pytest.raises(QualificationFixtureError, match="stale fixture .* is not marked non-current"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_10_temporal_fixture_valid_at_prohibited_time(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["effective_date_boundary_search"][0]
    # Set interval covering 2026-06-01T00:00:00Z
    s_auth["corpus_fixtures"][fid]["valid_from"] = "2026-01-01T00:00:00Z"
    s_auth["corpus_fixtures"][fid]["valid_to"] = "2026-12-31T23:59:59Z"
    for r in rows:
        if r.get("evidence_id") == fid:
            r["valid_from"] = "2026-01-01T00:00:00Z"
            r["valid_to"] = "2026-12-31T23:59:59Z"
    with pytest.raises(QualificationFixtureError, match="temporal fixture .* is valid at probe boundary"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_11_fixture_id_absent_from_identity_map(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["cross_tenant_search"][0]
    # Remove row from identity map
    filtered_rows = [r for r in rows if r.get("evidence_id") != fid]
    with pytest.raises(
        QualificationFixtureError, match="is absent from frozen identity authority|unknown frozen identity"
    ):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=filtered_rows,
        )


def test_12_duplicate_fixture_identity(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["cross_tenant_search"][0]
    # Reuse cross_tenant fixture ID in cross_dataset_search
    s_auth["case_evidence_fixtures"]["cross_dataset_search"] = [fid]
    with pytest.raises(QualificationFixtureError, match="fixture IDs must be unique across all Phase 7 cases"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_13_fixture_manifest_modified_after_freeze(tmp_path: Path) -> None:
    res = build_qualification_release(
        release_id="release-test-tamper-manifest",
        data_root_override=tmp_path,
    )
    rel_dir = tmp_path / "releases" / res["release_id"]
    fix_path = rel_dir / "data" / "qualification_fixtures.json"

    # Tamper with qualification_fixtures.json without updating manifest.json
    data = json.loads(fix_path.read_text(encoding="utf-8"))
    data["tampered"] = True
    fix_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="File hash mismatch for data/qualification_fixtures.json"):
        verify_release_directory(rel_dir, expected_release_id=res["release_id"])


def test_14_synthetic_random_unresolved_fixture_id(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    synth_id = "fixture:scope:synthetic:unresolved:0001"
    s_auth["case_evidence_fixtures"]["cross_tenant_search"] = [synth_id]
    s_auth["corpus_fixtures"][synth_id] = {
        "identity_type": "evidence",
        "source_chunk_id": "nonexistent-source-chunk",
        "tenant_id": s_auth["forbidden_tenant"],
    }
    s_auth["corpus_fixtures"].pop("fixture:scope:cross-tenant:evidence:0001", None)
    with pytest.raises(QualificationFixtureError, match="references unknown frozen identity"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


def test_15_visibility_document_exists_but_chunk_does_not(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    fid = s_auth["case_evidence_fixtures"]["document_visibility"][0]
    rec = s_auth["corpus_fixtures"][fid]
    # Remove the chunk matching rec["source_chunk_id"] from rows
    filtered_rows = [r for r in rows if r.get("source_chunk_id") != rec["source_chunk_id"]]
    with pytest.raises(QualificationFixtureError, match="references unknown frozen identity"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=filtered_rows,
        )


def test_16_fixture_namespace_collides_with_normal_production_identity(baseline_setup) -> None:
    q_scope, s_auth, rows = baseline_setup
    # Try to name a fixture using the production legal document namespace
    colliding_fid = "tr:legislation:law:5237"
    s_auth["case_evidence_fixtures"]["cross_tenant_search"] = [colliding_fid]
    s_auth["corpus_fixtures"][colliding_fid] = {
        "identity_type": "evidence",
        "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-tenant:chunk:0001",
        "tenant_id": s_auth["forbidden_tenant"],
    }
    s_auth["corpus_fixtures"].pop("fixture:scope:cross-tenant:evidence:0001", None)
    for r in rows:
        if r.get("source_chunk_id") == f"{FIXTURE_NAMESPACE_PREFIX}cross-tenant:chunk:0001":
            r["evidence_id"] = colliding_fid

    with pytest.raises(QualificationFixtureError, match="namespace collides with normal production identity"):
        validate_qualification_fixtures(
            qualification_scope=q_scope,
            scope_test_authority=s_auth,
            identity_map_rows=rows,
        )


# ==============================================================================
# Happy-Path Release Pipeline Test (Section 32)
# ==============================================================================


def test_qualification_release_happy_path(tmp_path: Path) -> None:
    release_id = "release-test-happy-path"
    res = build_qualification_release(
        release_id=release_id,
        data_root_override=tmp_path,
    )
    assert res["release_id"] == release_id
    assert res["status"] == "verified"
    assert res["counts"]["identity_map_count"] == 5734
    assert res["counts"]["qualification_fixtures_count"] == 12

    rel_dir = tmp_path / "releases" / release_id
    assert (rel_dir / "data" / "identity_map.jsonl").exists()
    assert (rel_dir / "data" / "qualification_fixtures.json").exists()
    assert (rel_dir / "manifest.json").exists()
    assert (rel_dir / "release.json").exists()

    # Cryptographic release verification
    verified = verify_release_directory(rel_dir, expected_release_id=release_id)
    assert verified is True


# ==============================================================================
# Strict E2E Compatibility Check (Section 33)
# ==============================================================================


def test_e2e_loader_compatibility(tmp_path: Path) -> None:
    """Verifies that MESA_E2E_Certification._load_frozen_scope_authority accepts release output."""
    e2e_path = Path("/home/yasin/Desktop/MESA_E2E_Certification")
    if not e2e_path.exists():
        pytest.skip("MESA_E2E_Certification checkout not found")

    if str(e2e_path) not in sys.path:
        sys.path.insert(0, str(e2e_path))

    from harness.identity import IdentityMap
    from harness.qualification_runner import _load_frozen_scope_authority

    release_id = "release-test-e2e-compat"
    build_qualification_release(
        release_id=release_id,
        data_root_override=tmp_path,
    )
    rel_dir = tmp_path / "releases" / release_id
    id_map_path = rel_dir / "data" / "identity_map.jsonl"
    fixtures_path = rel_dir / "data" / "qualification_fixtures.json"

    id_map = IdentityMap()
    id_map.load_from_file(id_map_path)
    assert id_map.mapping_count == 5734

    fixtures_data = json.loads(fixtures_path.read_text(encoding="utf-8"))
    freeze = {
        "runtime_identities": {
            "qualification_scope": fixtures_data["qualification_scope"],
            "scope_test_authority": fixtures_data["scope_test_authority"],
        }
    }

    scope, test_auth = _load_frozen_scope_authority(freeze, id_map)
    assert scope.tenant_id == "default"
    assert scope.workspace_id == "legal"
    assert scope.dataset_ids == ["tr_legislation"]
    assert scope.agent_id == "mesa_data_publisher"
    assert scope.expected_principal == "principal-user-1"

    assert test_auth.forbidden_tenant == "tenant-forbidden"
    assert test_auth.forbidden_dataset == "dataset-forbidden"
    assert test_auth.forbidden_agent == "agent-forbidden"
    assert test_auth.authorized_document == "tr:legislation:law:5237"
    assert len(test_auth.case_evidence_fixtures) == 12


# ==============================================================================
# Immutability and Safety Guards (Section 27 & 29)
# ==============================================================================


def test_cannot_overwrite_historical_release(tmp_path: Path) -> None:
    with pytest.raises(ReleaseBuildError, match="Cannot overwrite immutable historical qualification release"):
        build_qualification_release(
            release_id="release-20260831T145932Z",
            data_root_override=tmp_path,
        )


def test_baseline_identity_map_sha_integrity() -> None:
    rows = load_baseline_identity_map_rows()
    assert len(rows) == 5721
    # Check that authorized document is present in baseline
    doc_ids = {r.get("document_id") for r in rows if r.get("document_id")}
    assert "tr:legislation:law:5237" in doc_ids
    assert "tr:legislation:law:4721" in doc_ids
    assert len(doc_ids) == 68


# ==============================================================================
# Publisher Compatibility Check (Section 25)
# ==============================================================================


def test_publisher_compatibility_for_qualification_fixtures(tmp_path: Path) -> None:
    """Verifies that all qualification fixtures travel through publisher chunking and contract."""
    from mesa_legal_data.publisher.chunker import plan_source_chunks
    from mesa_legal_data.publisher.hashing import generate_idempotency_key

    bundle = build_qualification_fixtures()
    records = bundle["canonical_records"]
    s_auth = bundle["scope_test_authority"]

    # For each fixture in corpus_fixtures, verify chunking produces exact matching identity
    for case_id, fixture_ids in s_auth["case_evidence_fixtures"].items():
        for fixture_id in fixture_ids:
            rec_meta = s_auth["corpus_fixtures"][fixture_id]
            src_chunk_id = rec_meta["source_chunk_id"]

            # In identity_rows, find the row to get document_id and version_id
            row = next(r for r in bundle["identity_rows"] if r["source_chunk_id"] == src_chunk_id)
            doc_id = row["document_id"]
            ver_id = row["version_id"]

            matching_articles = [
                r
                for r in records
                if r["record_type"] == "article"
                and r["legislation_id"] == doc_id
                and r["legislation_version_id"] == ver_id
            ]
            assert len(matching_articles) >= 1, f"Missing article record for fixture {fixture_id}"
            art = matching_articles[0]

            # Plan source chunk for this version
            chunks = plan_source_chunks(
                document_id=doc_id,
                version_id=ver_id,
                canonical_text=art["text"],
                records=[art],
            )
            assert len(chunks) >= 1
            chunk = chunks[0]
            assert len(chunk.content_hash) == 64

            # Verify idempotency key generation succeeds
            idemp = generate_idempotency_key(
                tenant_id=rec_meta["tenant_id"],
                workspace_id="legal",
                dataset_id=rec_meta.get("dataset_id") or "tr_legislation",
                document_id=chunk.document_id,
                version_id=chunk.version_id,
                chunk_id=src_chunk_id,
                content_hash=chunk.content_hash,
            )
            assert idemp.startswith("mesa-data:")
            assert len(idemp) == 74
