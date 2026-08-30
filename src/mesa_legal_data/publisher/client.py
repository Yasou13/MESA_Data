import os
import time
from typing import Any
from urllib.parse import urlparse

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

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "MESA-Legal-Data-Publisher/1.0",
        }
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    def target_safety_error(self) -> str | None:
        """Validate the target before a request can carry the API key."""
        try:
            parsed = urlparse(self.settings.base_url)
        except ValueError:
            return "MESA target URL is malformed"
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return "MESA target URL is malformed or contains forbidden userinfo/query data"
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if host in local_hosts:
            if parsed.scheme != "http" and parsed.scheme != "https":
                return "Local MESA target must use HTTP or HTTPS"
            return None
        if parsed.scheme != "https":
            return "Non-local MESA target must use HTTPS"
        allowed_host = os.environ.get("MESA_DATA_MESA_ALLOWED_HOST", "").lower().rstrip(".")
        if not allowed_host:
            return "MESA_DATA_MESA_ALLOWED_HOST must explicitly allow the HTTPS target host"
        if host != allowed_host:
            return "MESA target host is not the explicitly allowed host"
        return None

    @property
    def is_contract_configured(self) -> bool:
        return bool(
            self.settings.contract_source in ("configured", "live_verified")
            and self.settings.base_url
            and self.settings.health_path.startswith("/")
            and self.settings.session_start_path.startswith("/")
            and self.settings.publish_path.startswith("/")
            and self.settings.mutation_status_path_template.startswith("/")
            and "{mutation_id}" in self.settings.mutation_status_path_template
        )

    @staticmethod
    def _normalize_mutation_state(raw_state: Any) -> tuple[str, str | None]:
        """Normalize known states without ever inferring COMMITTED."""
        if not isinstance(raw_state, str) or not raw_state.strip():
            return MutationState.FAILED.value, "MESA response did not include an explicit mutation state"
        state_upper = raw_state.strip().upper()
        if state_upper in ("ACCEPTED", "RECEIVED"):
            return MutationState.QUEUED.value, None
        if state_upper in (
            "EXTRACTED",
            "VALIDATED",
            "SQL_APPLIED",
            "VECTOR_APPLIED",
            "GRAPH_APPLIED",
            "RETRY_PENDING",
            "ROLLING_BACK",
        ):
            return MutationState.PROCESSING.value, None
        if state_upper in ("DEAD_LETTER", "BLOCKED", "ROLLED_BACK"):
            return MutationState.FAILED.value, None
        if state_upper in MutationState.__members__:
            return state_upper, None
        return MutationState.FAILED.value, f"Unknown MESA mutation state: {raw_state}"

    def test_connection(self) -> dict[str, Any]:
        """
        Tests connectivity to the configured MESA base_url.
        """
        target_error = self.target_safety_error()
        if target_error:
            return {
                "connected": False,
                "reachable": False,
                "authenticated": False,
                "latency_ms": 0.0,
                "details": target_error,
            }
        if not self.is_contract_configured:
            return {
                "connected": False,
                "reachable": False,
                "authenticated": False,
                "latency_ms": 0.0,
                "details": "MESA HTTP contract routes are not configured or verified",
            }

        start_time = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                url = self.settings.base_url.rstrip("/")
                resp = client.get(f"{url}{self.settings.health_path}", headers=self._get_headers())

                latency_ms = (time.perf_counter() - start_time) * 1000.0

                if resp.status_code in (200, 204):
                    return {
                        "connected": True,
                        "reachable": True,
                        "authenticated": True,
                        "latency_ms": round(latency_ms, 2),
                        "details": f"Connected ({resp.status_code})",
                    }
                elif resp.status_code in (401, 403):
                    return {
                        "connected": False,
                        "reachable": True,
                        "authenticated": False,
                        "latency_ms": round(latency_ms, 2),
                        "details": "Server reachable, authentication required",
                    }
                else:
                    return {
                        "connected": False,
                        "reachable": True,
                        "authenticated": False,
                        "latency_ms": round(latency_ms, 2),
                        "details": f"Server responded with status {resp.status_code}",
                    }
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "connected": False,
                "reachable": False,
                "authenticated": False,
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
        unreadable_versions_count: int = 0,
    ) -> PreflightReport:
        """
        Executes preflight verification checks against MESA v4 publisher requirements.
        """
        checks: list[PreflightCheckItem] = []

        # 1. Target URL Check
        target_error = self.target_safety_error()
        if not target_error:
            checks.append(
                PreflightCheckItem(
                    name="target_url", status="PASS", message=f"Target URL configured: {self.settings.base_url}"
                )
            )
        else:
            checks.append(PreflightCheckItem(name="target_url", status="FAIL", message=target_error))

        if self.is_contract_configured:
            checks.append(
                PreflightCheckItem(
                    name="http_contract",
                    status="PASS",
                    message=f"MESA HTTP contract is {self.settings.contract_source}",
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="http_contract",
                    status="FAIL",
                    message="MESA HTTP routes are unknown; configure a documented or live-verified contract",
                )
            )

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
        elif conn_res.get("reachable") and not conn_res.get("authenticated"):
            checks.append(
                PreflightCheckItem(
                    name="connectivity",
                    status="FAIL",
                    message=f"Server reachable but authentication failed ({conn_res['details']})",
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
        if unreadable_versions_count > 0:
            checks.append(
                PreflightCheckItem(
                    name="canonical_integrity",
                    status="FAIL",
                    message=f"{unreadable_versions_count} approved versions failed canonical integrity checks",
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="canonical_integrity", status="PASS", message="All planned canonical versions are readable"
                )
            )

        if blocked_versions_count > 0 and ready_versions_count == 0:
            checks.append(
                PreflightCheckItem(
                    name="quality_guard",
                    status="FAIL",
                    message=f"No current eligible versions; {blocked_versions_count} current versions are BLOCK and excluded",
                )
            )
        elif ready_versions_count > 0:
            checks.append(
                PreflightCheckItem(
                    name="quality_guard",
                    status="PASS",
                    message=(
                        f"{ready_versions_count} approved current versions ready for publishing ({estimated_chunks_count} chunks)"
                        + (
                            f"; {blocked_versions_count} current BLOCK versions excluded"
                            if blocked_versions_count
                            else ""
                        )
                    ),
                )
            )
        else:
            checks.append(
                PreflightCheckItem(
                    name="quality_guard",
                    status="FAIL",
                    message="No approved, readable versions are pending publication",
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

    def start_session(self) -> dict[str, Any]:
        """Create one MESA V4 session scoped to this delivery target."""
        if not self.is_contract_configured:
            return {"session_id": None, "error": "MESA HTTP contract is unknown"}
        target_error = self.target_safety_error()
        if target_error:
            return {"session_id": None, "error": target_error}
        payload = {
            "tenant_id": self.settings.tenant_id,
            "workspace_id": self.settings.workspace_id,
            "dataset_ids": [self.settings.dataset_id],
            "agent_id": self.settings.agent_id,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.settings.base_url.rstrip('/')}{self.settings.session_start_path}",
                    json=payload,
                    headers=self._get_headers(),
                )
                if response.status_code == 201:
                    data = response.json()
                    session_id = data.get("session_id")
                    if isinstance(session_id, str) and session_id:
                        return {"session_id": session_id, "message": data.get("status", "started")}
                    return {"session_id": None, "error": "MESA session start response omitted session_id"}
                return {"session_id": None, "error": f"HTTP {response.status_code}: {response.text[:200]}"}
        except Exception as exc:
            return {"session_id": None, "error": f"Transport failure starting session: {exc}"}

    def end_session(self, session_id: str) -> dict[str, Any]:
        """End a session only once no mutation needs it for status access."""
        if not session_id or not self.settings.session_end_path_template:
            return {"ended": False, "error": "Missing session_id or session end route"}
        path = self.settings.session_end_path_template.replace("{session_id}", session_id)
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.settings.base_url.rstrip('/')}{path}", headers=self._get_headers())
                return {
                    "ended": response.status_code in (200, 202),
                    "error": None
                    if response.status_code in (200, 202)
                    else f"HTTP {response.status_code}: {response.text[:200]}",
                }
        except Exception as exc:
            return {"ended": False, "error": f"Transport failure ending session: {exc}"}

    def build_memory_insert_payload(
        self,
        chunk: SourceChunk,
        *,
        session_id: str,
        idempotency_key: str,
        finalize_revision: bool,
    ) -> dict[str, Any]:
        """Map a frozen source chunk to the strict V4MemoryInsertRequest shape."""
        metadata = {
            **chunk.metadata,
            "mesa_data_chunk_type": chunk.chunk_type,
            "mesa_data_char_start": chunk.char_start,
            "mesa_data_char_end": chunk.char_end,
            "mesa_data_content_hash": chunk.content_hash,
        }
        source_ref = metadata.get("authoritative_source_ref") or metadata.get("source_url")
        if not isinstance(source_ref, str) or not source_ref.strip():
            source_ref = f"mesa-data://releases/{metadata.get('release_id', 'current')}/documents/{chunk.document_id}/revisions/{chunk.version_id}/chunks/{chunk.chunk_id}"
        return {
            "session_id": session_id,
            "dataset_id": self.settings.dataset_id,
            "document_id": chunk.document_id,
            "revision_id": chunk.version_id,
            "chunk_id": chunk.chunk_id,
            "title": chunk.title or f"Document {chunk.document_id} chunk {chunk.ordinal}",
            "source_ref": source_ref,
            "content": chunk.content,
            "evidence_span": "",
            "revision_number": int(metadata.get("revision_number", 1)),
            "chunk_ordinal": chunk.ordinal,
            "finalize_revision": finalize_revision,
            "supersedes_revision_id": metadata.get("supersedes_revision_id"),
            "metadata": metadata,
            "idempotency_key": idempotency_key,
        }

    def publish_source_chunk(
        self,
        chunk: SourceChunk,
        idempotency_key: str,
        *,
        session_id: str,
        finalize_revision: bool,
    ) -> dict[str, Any]:
        """Submit one strict V4MemoryInsertRequest to MESA."""
        payload = self.build_memory_insert_payload(
            chunk,
            session_id=session_id,
            idempotency_key=idempotency_key,
            finalize_revision=finalize_revision,
        )

        if not self.is_contract_configured:
            return {
                "mutation_id": None,
                "state": MutationState.FAILED.value,
                "message": "MESA HTTP contract is unknown; refusing to guess a publish route",
            }

        target_error = self.target_safety_error()
        if target_error:
            return {"mutation_id": None, "state": MutationState.FAILED.value, "message": target_error}

        url = f"{self.settings.base_url.rstrip('/')}{self.settings.publish_path}"
        headers = self._get_headers()

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code in (200, 201, 202):
                    data = resp.json()
                    mutation_id = data.get("mutation_id") or data.get("id")
                    state_upper, state_error = self._normalize_mutation_state(data.get("state") or data.get("status"))
                    if state_upper in (MutationState.QUEUED.value, MutationState.PROCESSING.value) and not mutation_id:
                        state_upper = MutationState.FAILED.value
                        state_error = "MESA returned a non-terminal state without mutation_id"
                    return {
                        "mutation_id": mutation_id,
                        "state": state_upper,
                        "message": state_error or data.get("message", "Mutation accepted"),
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

        if not self.is_contract_configured:
            return {
                "mutation_id": mutation_id,
                "state": MutationState.FAILED.value,
                "error": "MESA HTTP contract is unknown",
            }

        target_error = self.target_safety_error()
        if target_error:
            return {"mutation_id": mutation_id, "state": MutationState.FAILED.value, "error": target_error}

        mutation_path = self.settings.mutation_status_path_template.replace("{mutation_id}", mutation_id)
        url = f"{self.settings.base_url.rstrip('/')}{mutation_path}"
        headers = self._get_headers()

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    state_upper, state_error = self._normalize_mutation_state(data.get("state") or data.get("status"))
                    return {
                        "mutation_id": mutation_id,
                        "state": state_upper,
                        "error": state_error or data.get("error"),
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
