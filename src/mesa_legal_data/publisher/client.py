import os
import time
from typing import Any

import httpx

from mesa_legal_data.publisher.models import (
    MesaTargetSettings,
    MutationState,
    PreflightCheckItem,
    PreflightReport,
    SourceChunk,
)


class MesaClientError(Exception):
    """Base error for MESA client interactions."""


class MesaClient:
    """
    Minimal, robust HTTP client for MESA v4 API.
    Reads API key strictly from environment secret (MESA_DATA_MESA_API_KEY / MESA_API_KEY).
    Never logs or persists the API key.
    """

    def __init__(
        self,
        settings: MesaTargetSettings,
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
    ):
        self.settings = settings
        self._api_key = api_key or os.environ.get("MESA_DATA_MESA_API_KEY") or os.environ.get("MESA_API_KEY")
        self.timeout_seconds = timeout_seconds

    @property
    def is_api_key_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def _get_headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MESA-Legal-Data-Publisher/1.0",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def test_connection(self) -> dict[str, Any]:
        """
        Tests connectivity to the configured MESA base_url.
        """
        if not self.settings.base_url:
            return {"connected": False, "latency_ms": 0.0, "details": "Base URL not configured"}

        start_time = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                # Try v4 health, then root health
                url = self.settings.base_url.rstrip("/")
                resp = None
                for path in ["/v4/health", "/health", "/"]:
                    try:
                        resp = client.get(f"{url}{path}", headers=self._get_headers())
                        if resp.status_code in (200, 204, 401, 403):
                            break
                    except Exception:
                        continue

                latency_ms = (time.perf_counter() - start_time) * 1000.0

                if resp is None:
                    return {
                        "connected": False,
                        "latency_ms": round(latency_ms, 2),
                        "details": f"Could not reach {self.settings.base_url}",
                    }

                if resp.status_code in (200, 204):
                    return {
                        "connected": True,
                        "latency_ms": round(latency_ms, 2),
                        "details": f"Connected ({resp.status_code})",
                    }
                elif resp.status_code in (401, 403):
                    return {
                        "connected": True,
                        "latency_ms": round(latency_ms, 2),
                        "details": "Server reachable, authentication required",
                    }
                else:
                    return {
                        "connected": False,
                        "latency_ms": round(latency_ms, 2),
                        "details": f"Server responded with status {resp.status_code}",
                    }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "connected": False,
                "latency_ms": round(latency_ms, 2),
                "details": f"Connection error: {e}",
            }

    def run_preflight_checks(
        self,
        ready_documents_count: int = 0,
        ready_versions_count: int = 0,
        estimated_chunks_count: int = 0,
        total_canonical_bytes: int = 0,
        blocked_versions_count: int = 0,
    ) -> PreflightReport:
        """
        Executes preflight verification checks against MESA v4 publisher requirements.
        """
        checks: list[PreflightCheckItem] = []

        # 1. Target URL Check
        if self.settings.base_url and self.settings.base_url.startswith(("http://", "https://")):
            checks.append(
                PreflightCheckItem(
                    name="target_url", status="PASS", message=f"Target URL configured: {self.settings.base_url}"
                )
            )
        else:
            checks.append(PreflightCheckItem(name="target_url", status="FAIL", message="Invalid or missing target URL"))

        # 2. API Key Check
        if self.is_api_key_configured:
            checks.append(
                PreflightCheckItem(
                    name="api_key", status="PASS", message="API Key is configured via environment secret"
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="api_key", status="WARN", message="API Key not configured (required if auth is enabled)"
                )
            )

        # 3. Target Identifiers Check
        missing_ids = []
        for f in ["tenant_id", "workspace_id", "dataset_id", "agent_id"]:
            if not getattr(self.settings, f, "").strip():
                missing_ids.append(f)
        if not missing_ids:
            checks.append(
                PreflightCheckItem(
                    name="target_scope",
                    status="PASS",
                    message=f"Target scope valid ({self.settings.tenant_id}/{self.settings.workspace_id}/{self.settings.dataset_id})",
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="target_scope",
                    status="FAIL",
                    message=f"Missing required target identifiers: {', '.join(missing_ids)}",
                )
            )

        # 4. Server Reachability Check
        conn_res = self.test_connection()
        if conn_res["connected"]:
            checks.append(
                PreflightCheckItem(
                    name="connectivity",
                    status="PASS",
                    message=f"Server reachable ({conn_res['details']}, {conn_res['latency_ms']}ms)",
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="connectivity",
                    status="FAIL",
                    message=f"Cannot reach server: {conn_res['details']}",
                )
            )

        # 5. Quality & Release Readiness Check
        if blocked_versions_count > 0:
            checks.append(
                PreflightCheckItem(
                    name="quality_guard",
                    status="FAIL",
                    message=f"{blocked_versions_count} versions have quality status BLOCK (excluded from delivery)",
                )
            )
        elif ready_versions_count > 0:
            checks.append(
                PreflightCheckItem(
                    name="quality_guard",
                    status="PASS",
                    message=f"{ready_versions_count} approved versions ready for publishing ({estimated_chunks_count} chunks)",
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="quality_guard",
                    status="WARN",
                    message="No approved versions currently pending publication",
                )
            )

        overall_pass = all(c.status != "FAIL" for c in checks)
        return PreflightReport(
            overall_status="PASS" if overall_pass else "FAIL",
            checks=checks,
            ready_documents_count=ready_documents_count,
            ready_versions_count=ready_versions_count,
            estimated_chunks_count=estimated_chunks_count,
            total_canonical_bytes=total_canonical_bytes,
        )

    def publish_source_chunk(
        self,
        chunk: SourceChunk,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """
        Submits a single source chunk mutation to MESA v4 HTTP API.
        Returns dictionary with mutation_id, state (COMMITTED, QUEUED, etc.), and message.
        """
        payload = {
            "tenant_id": self.settings.tenant_id,
            "workspace_id": self.settings.workspace_id,
            "dataset_id": self.settings.dataset_id,
            "agent_id": self.settings.agent_id,
            "document_id": chunk.document_id,
            "version_id": chunk.version_id,
            "chunk_id": chunk.chunk_id,
            "chunk_type": chunk.chunk_type,
            "title": chunk.title,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "ordinal": chunk.ordinal,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "metadata": chunk.metadata,
        }

        url = f"{self.settings.base_url.rstrip('/')}/v4/sources/chunks"
        headers = self._get_headers(idempotency_key=idempotency_key)

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code in (200, 201, 202):
                    data = resp.json()
                    mutation_id = data.get("mutation_id") or data.get("id") or f"mut-{chunk.chunk_id}"
                    # Check explicit mutation status from response
                    state = data.get("state") or data.get("status") or "COMMITTED"
                    state_upper = state.upper()
                    if state_upper not in MutationState.__members__:
                        state_upper = "COMMITTED"
                    return {
                        "mutation_id": mutation_id,
                        "state": state_upper,
                        "message": data.get("message", "Mutation accepted"),
                    }
                elif resp.status_code == 422:
                    # Semantic rejection
                    error_msg = resp.text
                    try:
                        error_msg = resp.json().get("detail", error_msg)
                    except Exception:
                        pass
                    return {
                        "mutation_id": None,
                        "state": MutationState.REJECTED.value,
                        "message": f"MESA rejected payload (422): {error_msg}",
                    }
                else:
                    return {
                        "mutation_id": None,
                        "state": MutationState.FAILED.value,
                        "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    }
        except Exception as e:
            return {
                "mutation_id": None,
                "state": MutationState.FAILED.value,
                "message": f"Transport failure: {e}",
            }

    def get_mutation_status(self, mutation_id: str) -> dict[str, Any]:
        """
        Polls status of an async mutation identifier.
        """
        if not mutation_id:
            return {"mutation_id": mutation_id, "state": MutationState.FAILED.value, "error": "Missing mutation_id"}

        url = f"{self.settings.base_url.rstrip('/')}/v4/mutations/{mutation_id}"
        headers = self._get_headers()

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_state = data.get("state") or data.get("status") or "COMMITTED"
                    state_upper = raw_state.upper()
                    if state_upper not in MutationState.__members__:
                        state_upper = "COMMITTED"
                    return {
                        "mutation_id": mutation_id,
                        "state": state_upper,
                        "error": data.get("error"),
                    }
                else:
                    return {
                        "mutation_id": mutation_id,
                        "state": MutationState.FAILED.value,
                        "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    }
        except Exception as e:
            return {
                "mutation_id": mutation_id,
                "state": MutationState.FAILED.value,
                "error": f"Transport error polling mutation {mutation_id}: {e}",
            }
