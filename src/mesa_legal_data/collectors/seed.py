from datetime import UTC, datetime
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from mesa_legal_data.catalog import get_connection, get_document
from mesa_legal_data.models import FetchedArtifact
from mesa_legal_data.pipeline import process_artifact_pipeline
from mesa_legal_data.sources import import_manual_file, import_manual_url
from mesa_legal_data.sources.request_control import reset_run_budget


def load_seed_config(config_path: Path | None = None) -> list[dict]:
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "seed_legislation.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Seed configuration file not found at {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data.get("seed_legislation", [])


def run_seed_collection(
    config_path: Path | None = None,
    local_fixtures_dir: Path | None = None,
) -> list[FetchedArtifact]:
    """
    Collects seed legislation. If local_fixtures_dir is provided, imports from local files;
    otherwise imports via URL. Continues on individual item failures and reports them.
    Runs process_artifact_pipeline for every artifact that is new in this run.
    Prints, per item: number, title, collected / unchanged / failed, pipeline status.
    """
    items = load_seed_config(config_path)
    collected: list[FetchedArtifact] = []

    today_utc = datetime.now(UTC).strftime("%Y-%m-%d")
    extra_meta = {
        "snapshot_date": today_utc,
        "source_role": "consolidated_text",
    }

    for item in items:
        doc_id = item["document_id"]
        number = item["number"]
        title = item["title"]
        doc_type = item.get("type", "law")
        family = "legislation"
        source_id = "mevzuat"

        try:
            reset_run_budget(source_id)
            conn = get_connection()
            try:
                document = get_document(conn, doc_id)
            finally:
                conn.close()
            item_metadata = dict(extra_meta)
            if document and document["current_version_id"]:
                item_metadata["supersedes_version_id"] = document["current_version_id"]
            if local_fixtures_dir and (local_fixtures_dir / f"{number}.pdf").exists():
                fixture_file = local_fixtures_dir / f"{number}.pdf"
                artifact = import_manual_file(
                    file_path=fixture_file,
                    source_id=source_id,
                    document_id=doc_id,
                    family=family,
                    document_type=doc_type,
                    title=title,
                    extra_metadata=item_metadata,
                )
            else:
                source_url = item["source_url"]
                artifact = import_manual_url(
                    url=source_url,
                    source_id=source_id,
                    document_id=doc_id,
                    family=family,
                    document_type=doc_type,
                    title=title,
                    extra_metadata=item_metadata,
                )

            is_dup = getattr(artifact, "is_duplicate", False)
            if is_dup:
                item_status = "unchanged"
                pipe_status = "skipped"
            else:
                item_status = "collected"
                try:
                    pipe_status = process_artifact_pipeline(artifact.artifact_id)
                except Exception as p_err:
                    pipe_status = f"pipeline error: {p_err}"

            collected.append(artifact)
            print(f"{number} {title}: {item_status}, pipeline: {pipe_status}")

        except Exception as e:
            err_msg = str(e)
            if "already exists" in err_msg.lower() or "unique constraint" in err_msg.lower():
                print(f"{number} {title}: unchanged, pipeline: skipped")
            else:
                print(f"{number} {title}: failed, pipeline: skipped ({err_msg[:80]})")
            continue

    return collected
