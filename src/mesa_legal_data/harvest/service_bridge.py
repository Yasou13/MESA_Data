from pathlib import Path

from mesa_legal_data.content_types import ContentTypeError, SizeLimitError
from mesa_legal_data.harvest.models import CollectResult, HarvestItem, PipelineResult
from mesa_legal_data.pipeline import InvalidStateTransition, process_artifact_pipeline
from mesa_legal_data.schema_validation import SchemaValidationError
from mesa_legal_data.sources.manual import import_manual_url
from mesa_legal_data.sources.url_fetcher import (
    SourcePolicyError,
    SSRFError,
    URLFetchError,
)


class ServiceBridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def collect_url_item(item: HarvestItem, sources_yaml_path: Path | None = None) -> CollectResult:
    """
    Invokes core import_manual_url with source policy, SSRF checks, hash verification,
    and storage in core raw directory + catalog.sqlite.
    """
    try:
        artifact = import_manual_url(
            url=item.original_url,
            source_id=item.source_id,
            document_id=item.document_id,
            family=item.family,
            document_type=item.document_type,
            jurisdiction="TR",
            title=item.title,
            stable_key=item.document_id,
            sources_yaml_path=sources_yaml_path,
        )
        return CollectResult(
            artifact_id=artifact.artifact_id,
            document_id=artifact.document_id or item.document_id,
            byte_size=artifact.byte_size,
            duplicate=artifact.is_duplicate,
        )
    except Exception as e:
        err_msg = str(e)
        err_code = "DOWNLOAD_FAILED"
        if isinstance(e, SourcePolicyError):
            err_code = "SOURCE_POLICY_VIOLATION"
            if "Host" in err_msg and "not allowed" in err_msg:
                err_code = "SOURCE_HOST_NOT_ALLOWED"
            elif "disabled" in err_msg.lower():
                err_code = "SOURCE_DISABLED"
            elif "content type" in err_msg.lower() or "mime" in err_msg.lower():
                err_code = "SOURCE_CONTENT_TYPE_NOT_ALLOWED"
        elif isinstance(e, SSRFError):
            err_code = "SSRF_VIOLATION"
        elif isinstance(e, (SizeLimitError, ContentTypeError)):
            if "size" in err_msg.lower() or "large" in err_msg.lower():
                err_code = "FILE_TOO_LARGE"
            else:
                err_code = "SOURCE_CONTENT_TYPE_NOT_ALLOWED"
        elif isinstance(e, URLFetchError):
            err_code = "HTTP_FETCH_FAILED"
            if "timeout" in err_msg.lower():
                err_code = "HTTP_TIMEOUT"
            elif "404" in err_msg:
                err_code = "HTTP_404"
            elif "429" in err_msg:
                err_code = "HTTP_429"
            elif any(s in err_msg for s in ("500", "502", "503", "504")):
                err_code = "HTTP_SERVER_ERROR"
        else:
            if "Host" in err_msg and "not allowed" in err_msg:
                err_code = "SOURCE_HOST_NOT_ALLOWED"
            elif "disabled" in err_msg.lower():
                err_code = "SOURCE_DISABLED"
            elif "content type" in err_msg.lower() or "mime" in err_msg.lower():
                err_code = "SOURCE_CONTENT_TYPE_NOT_ALLOWED"
            elif "too large" in err_msg.lower() or "size" in err_msg.lower():
                err_code = "FILE_TOO_LARGE"
            elif "timeout" in err_msg.lower():
                err_code = "HTTP_TIMEOUT"
            elif "404" in err_msg:
                err_code = "HTTP_404"
            elif "429" in err_msg:
                err_code = "HTTP_429"

        raise ServiceBridgeError(code=err_code, message=err_msg) from e


def run_pipeline_item(artifact_id: str) -> PipelineResult:
    """
    Invokes core process_artifact_pipeline for canonical extraction, schema validation, and privacy checks.
    """
    try:
        final_status = process_artifact_pipeline(artifact_id)

        version_id = None
        record_count = None
        try:
            from mesa_legal_data.catalog import get_artifact, get_connection, get_document

            conn = get_connection()
            art = get_artifact(conn, artifact_id)
            if art and art.get("document_id"):
                doc = get_document(conn, art["document_id"])
                if doc and doc.get("current_version_id"):
                    version_id = doc["current_version_id"]
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM records WHERE version_id = ?", (version_id,))
                    row = cursor.fetchone()
                    if row:
                        record_count = row[0]
            conn.close()
        except Exception:
            pass

        return PipelineResult(
            artifact_id=artifact_id,
            version_id=version_id,
            status=final_status,
            record_count=record_count,
            issue_counts=None,
        )
    except Exception as e:
        err_msg = str(e)
        err_code = "PIPELINE_FAILED"
        if isinstance(e, InvalidStateTransition):
            err_code = "INVALID_STATE_TRANSITION"
        elif isinstance(e, SchemaValidationError):
            err_code = "SCHEMA_VALIDATION_FAILED"
        elif "InvalidStateTransition" in err_msg:
            err_code = "INVALID_STATE_TRANSITION"
        elif "Schema" in err_msg or "schema" in err_msg:
            err_code = "SCHEMA_VALIDATION_FAILED"
        elif "parse" in err_msg.lower():
            err_code = "PARSING_FAILED"

        raise ServiceBridgeError(code=err_code, message=err_msg) from e
