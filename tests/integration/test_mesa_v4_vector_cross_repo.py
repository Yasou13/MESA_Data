"""Optional real-storage compatibility proof against the current MESA checkout."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

# The authoritative MESA checkout currently uses Python 3.10 while MESA_Data
# itself requires 3.11+.  Supply the standard 3.11 UTC alias so the newer
# producer package can be imported by MESA's dependency environment.
if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc  # type: ignore[attr-defined]

from mesa_legal_data.publisher.chunker import plan_source_chunks
from mesa_legal_data.publisher.client import MesaClient
from mesa_legal_data.publisher.models import MesaTargetSettings

MESA_SOURCE_ROOT = os.environ.get("MESA_SOURCE_ROOT")
if not MESA_SOURCE_ROOT:
    pytest.skip("set MESA_SOURCE_ROOT to run cross-repository compatibility", allow_module_level=True)

mesa_root = Path(MESA_SOURCE_ROOT).resolve()
if not (mesa_root / "mesa_storage" / "representation.py").is_file():
    pytest.skip("MESA_SOURCE_ROOT is not a MESA source checkout", allow_module_level=True)
sys.path.insert(0, str(mesa_root))

from mesa_memory.config import config, configured_embedding_identity  # noqa: E402
from mesa_memory.embedding.service import (  # noqa: E402
    EmbeddingIdentity,
    EmbeddingService,
)
from mesa_storage.dao import MemoryDAO  # noqa: E402
from mesa_storage.kuzu_provider import KuzuGraphProvider  # noqa: E402
from mesa_storage.kuzu_setup import initialize_schema_artifact  # noqa: E402
from mesa_storage.representation import (  # noqa: E402
    V4_VECTOR_REPRESENTATION_VERSION,
)
from mesa_storage.schemas import initialize_schema  # noqa: E402
from mesa_storage.sqlite_engine import AsyncEngine  # noqa: E402
from mesa_storage.vector_engine import VectorEngine  # noqa: E402
from mesa_workers.ingestion_worker import process_cold_path  # noqa: E402
from mesa_workers.projection_worker import process_projection_outbox_once  # noqa: E402


def _semantic_vector(text: str) -> list[float]:
    """Small deterministic semantic fixture in the configured vector dimension."""
    folded = text.casefold()
    vector = [0.0] * 768
    if "gelmeden görev" in folded or "uzaktan mesai" in folded:
        vector[0] = 1.0
    elif "arşiv kayıtları" in folded or "saklama süresi" in folded:
        vector[1] = 1.0
    else:
        vector[2] = 1.0
    return vector


@pytest.mark.cross_repo
@pytest.mark.asyncio
async def test_mesa_data_chunks_produce_current_mesa_vector_artifacts(tmp_path: Path) -> None:
    runtime_identity = configured_embedding_identity()
    assert runtime_identity.provider == "local"
    assert runtime_identity.model == "magibu/embeddingmagibu-200m"
    assert runtime_identity.dimension == 768

    identity = EmbeddingIdentity(
        provider=runtime_identity.provider,
        model=runtime_identity.model,
        version=runtime_identity.version,
        dimension=runtime_identity.dimension,
        normalized=runtime_identity.normalized,
        model_revision=runtime_identity.model_revision,
    )
    service = EmbeddingService(
        identity=identity,
        provider_fn=_semantic_vector,
        query_provider_fn=_semantic_vector,
    )
    sql = AsyncEngine(str(tmp_path / "mesa.sqlite"))
    vector = VectorEngine(
        str(tmp_path / "vectors.lance"),
        max_workers=1,
        embedding_service=service,
    )
    graph_path = tmp_path / "graph"
    await sql.initialize()
    await initialize_schema(sql)
    await vector.initialize()
    initialize_schema_artifact(str(graph_path))
    graph = KuzuGraphProvider(str(graph_path), max_workers=1)
    await graph.initialize()
    dao = MemoryDAO(sqlite_engine=sql, vector_engine=vector, graph_provider=graph)

    settings = MesaTargetSettings(
        tenant_id="tenant-vector",
        workspace_id="workspace-vector",
        dataset_id="dataset-vector",
        agent_id="agent-vector",
    )
    client = MesaClient(settings, api_key="test-only")
    target_article = "MADDE 1- " + ("Genel açıklama. " * 18) + "Çalışanlar kurum binasına gelmeden görev yapabilir."
    distractor_article = "MADDE 2- Arşiv kayıtları yasal saklama süresi boyunca korunur."
    canonical_text = f"{target_article}\n\n{distractor_article}"
    second_start = len(target_article) + 2
    chunks = plan_source_chunks(
        document_id="law-remote-work",
        version_id="law-remote-work:v1",
        canonical_text=canonical_text,
        records=[
            {
                "record_id": "article-1",
                "record_type": "article",
                "article_number": "1",
                "title": "Madde 1",
                "char_start": 0,
                "char_end": len(target_article),
                "ordinal": 1,
            },
            {
                "record_id": "article-2",
                "record_type": "article",
                "article_number": "2",
                "title": "Madde 2",
                "char_start": second_start,
                "char_end": len(canonical_text),
                "ordinal": 2,
            },
        ],
    )
    assert len(chunks) == 2
    assert all(len(chunk.content) <= 4096 for chunk in chunks)

    try:
        await dao.ensure_v4_catalog_scope(
            tenant_id=settings.tenant_id,
            workspace_id=settings.workspace_id,
            dataset_id=settings.dataset_id,
        )
        admitted: list[tuple[int, str]] = []
        for index, chunk in enumerate(chunks):
            chunk.metadata.update(
                {
                    "release_id": "release-vector-v1",
                    "revision_number": 1,
                    "source_url": "https://authority.example/law/remote-work",
                    "source_id": "authority-law-remote-work",
                    "artifact_sha256": "a" * 64,
                    "is_final_chunk": index == len(chunks) - 1,
                }
            )
            payload = client.build_memory_insert_payload(
                chunk,
                session_id="session-vector",
                idempotency_key=f"vector-{index}",
                finalize_revision=index == len(chunks) - 1,
            )
            assert payload["evidence_span"] == payload["content"]
            admission_args = dict(
                tenant_id=settings.tenant_id,
                workspace_id=settings.workspace_id,
                dataset_id=settings.dataset_id,
                agent_id=settings.agent_id,
                session_id=payload["session_id"],
                document_id=payload["document_id"],
                revision_id=payload["revision_id"],
                chunk_id=payload["chunk_id"],
                title=payload["title"],
                content_payload=payload["content"],
                source_ref=payload["source_ref"],
                evidence_span=payload["evidence_span"],
                revision_number=payload["revision_number"],
                chunk_ordinal=payload["chunk_ordinal"],
                supersedes_revision_id=payload["supersedes_revision_id"],
                metadata=payload["metadata"],
                embedding_provider=identity.provider,
                embedding_model=identity.model,
                embedding_version=identity.version,
                embedding_dimension=identity.dimension,
                embedding_space_id=identity.embedding_space_id,
                embedding_model_revision=identity.model_revision,
                embedding_normalized=identity.normalized,
                policy=config.queue_admission_policy,
                validation_mode=0,
                idempotency_key=payload["idempotency_key"],
                payload_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                finalize_revision=payload["finalize_revision"],
            )
            result = await dao.admit_v4_memory(**admission_args)
            duplicate = await dao.admit_v4_memory(**admission_args)
            assert duplicate == {
                "outcome": "DUPLICATE",
                "response": result["response"],
            }
            mutation_id = result["response"]["mutation_id"]
            async with sql.connection() as db:
                async with db.execute(
                    "SELECT raw_log_id FROM memory_mutations WHERE mutation_id = ?",
                    (mutation_id,),
                ) as cursor:
                    raw_log_id = int((await cursor.fetchone())[0])
            admitted.append((raw_log_id, mutation_id))

        for raw_log_id, _mutation_id in admitted:
            await process_cold_path(
                raw_log_id,
                settings.agent_id,
                dao,
                model_processing_enabled=False,
            )

        for _ in range(12):
            outcome = await process_projection_outbox_once(dao, worker_id="cross-repo-vector", limit=1)
            if outcome["claimed"] == 0:
                break

        async with sql.connection() as db:
            async with db.execute(
                "SELECT r.registry_id, r.physical_artifact_id, r.metadata_json, "
                "s.dataset_id, s.document_id, s.revision_id, s.chunk_id, "
                "s.source_ref, s.evidence_span "
                "FROM artifact_registry r JOIN artifact_sources s "
                "ON s.registry_id = r.registry_id "
                "WHERE r.artifact_kind = 'ASSERTION_VECTOR' AND r.state = 'ACTIVE' "
                "ORDER BY s.chunk_id"
            ) as cursor:
                registry_rows = await cursor.fetchall()
            async with db.execute("SELECT assertion_id FROM v4_assertions WHERE status = 'ACTIVE'") as cursor:
                assertion_ids = {str(row[0]) for row in await cursor.fetchall()}

        assert len(registry_rows) == len(chunks) == 2
        registry_vector_ids = {str(row[1]) for row in registry_rows}
        assert registry_vector_ids == assertion_ids
        assert await vector.get_active_node_ids(settings.agent_id) == assertion_ids
        embeddings = await vector.get_all_embeddings(agent_id=settings.agent_id)
        assert len(embeddings) == 2
        assert {len(embedding) for embedding in embeddings} == {identity.dimension}
        for row in registry_rows:
            metadata = json.loads(row[2])
            assert metadata == {
                **identity.as_dict(),
                "embedding_dimension": identity.dimension,
                "representation_version": V4_VECTOR_REPRESENTATION_VERSION,
            }
            assert row[3]
            assert row[4]
            assert row[5]
            assert row[6]
            assert row[7] == "https://authority.example/law/remote-work"
            assert row[8]

        diagnostics: dict = {}
        results = await dao.search_v4_memory(
            tenant_id=settings.tenant_id,
            agent_id=settings.agent_id,
            dataset_ids=[settings.dataset_id],
            query="Personel için uzaktan mesai yetkisi",
            limit=10,
            certification_metadata=diagnostics,
        )
        assert results
        semantic_hit = next(result for result in results if "gelmeden görev" in result["evidence_span"].casefold())
        assert "vector" in semantic_hit["retrieval_provenance"]["origins"]
        assert semantic_hit["retrieval_provenance"]["vector"]["rank"] == 1
        assert semantic_hit["retrieval_provenance"]["vector"]["distance"] == 0.0
        assert diagnostics["vector_lane"]["status"] == "active"
        assert diagnostics["vector_lane"]["allowed_vector_id_count"] == 2
    finally:
        await graph.close()
        await vector.close()
        await sql.close()
