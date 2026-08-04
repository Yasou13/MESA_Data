from pathlib import Path

import yaml  # type: ignore[import-untyped]

from mesa_legal_data.models import FetchedArtifact
from mesa_legal_data.sources import import_manual_file, import_manual_url


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
    otherwise imports via URL.
    """
    items = load_seed_config(config_path)
    collected = []

    for item in items:
        doc_id = item["document_id"]
        number = item["number"]
        title = item["title"]
        doc_type = item.get("type", "law")
        family = "legislation"
        source_id = "mevzuat"

        if local_fixtures_dir and (local_fixtures_dir / f"{number}.pdf").exists():
            fixture_file = local_fixtures_dir / f"{number}.pdf"
            artifact = import_manual_file(
                file_path=fixture_file,
                source_id=source_id,
                document_id=doc_id,
                family=family,
                document_type=doc_type,
                title=title,
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
            )

        collected.append(artifact)

    return collected
