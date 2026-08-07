from dataclasses import dataclass, field
from pathlib import Path

import yaml  # type: ignore[import-untyped]


@dataclass
class HarvestTargetConfig:
    raw_bytes: int = 32212254720  # 30 GB
    stop_when_target_reached: bool = True
    minimum_free_disk_bytes: int = 53687091200  # 50 GB


@dataclass
class HarvestRunnerConfig:
    worker_count: int = 1
    batch_size: int = 25
    lease_seconds: int = 1800
    max_runtime_seconds: int = 1200
    max_attempts: int = 5
    pipeline_after_download: bool = True
    stop_on_error_rate: float = 0.25


@dataclass
class HarvestReviewConfig:
    auto_approve: bool = False
    weekly_sample_per_source: int = 50


@dataclass
class SelectionConfig:
    include_sections: list[str] = field(default_factory=list)
    exclude_sections: list[str] = field(default_factory=list)
    allowed_document_types: list[str] = field(default_factory=list)


@dataclass
class SourceBudgetConfig:
    target_raw_bytes: int = 5368709120
    daily_raw_bytes: int = 536870912
    daily_documents: int = 1000
    discovery_pages_per_run: int = 50
    new_urls_per_run: int = 1000


@dataclass
class HarvestSourceConfig:
    enabled: bool = True
    adapter: str = ""
    source_id: str = ""
    date_from: str | None = None
    date_to: str | None = None
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    budget: SourceBudgetConfig = field(default_factory=SourceBudgetConfig)


@dataclass
class HarvestConfig:
    enabled: bool = True
    target: HarvestTargetConfig = field(default_factory=HarvestTargetConfig)
    runner: HarvestRunnerConfig = field(default_factory=HarvestRunnerConfig)
    review: HarvestReviewConfig = field(default_factory=HarvestReviewConfig)
    sources: dict[str, HarvestSourceConfig] = field(default_factory=dict)


def load_harvest_config(config_path: Path | None = None) -> HarvestConfig:
    if config_path is None:
        config_path = Path("config/harvest.yaml")

    if not config_path.exists():
        return HarvestConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    harvest_data = data.get("harvest", {})
    target_data = harvest_data.get("target", {})
    runner_data = harvest_data.get("runner", {})
    review_data = harvest_data.get("review", {})

    target_cfg = HarvestTargetConfig(
        raw_bytes=target_data.get("raw_bytes", 32212254720),
        stop_when_target_reached=target_data.get("stop_when_target_reached", True),
        minimum_free_disk_bytes=target_data.get("minimum_free_disk_bytes", 53687091200),
    )

    runner_cfg = HarvestRunnerConfig(
        worker_count=runner_data.get("worker_count", 1),
        batch_size=runner_data.get("batch_size", 25),
        lease_seconds=runner_data.get("lease_seconds", 1800),
        max_runtime_seconds=runner_data.get("max_runtime_seconds", 1200),
        max_attempts=runner_data.get("max_attempts", 5),
        pipeline_after_download=runner_data.get("pipeline_after_download", True),
        stop_on_error_rate=runner_data.get("stop_on_error_rate", 0.25),
    )

    review_cfg = HarvestReviewConfig(
        auto_approve=review_data.get("auto_approve", False),
        weekly_sample_per_source=review_data.get("weekly_sample_per_source", 50),
    )

    sources_dict: dict[str, HarvestSourceConfig] = {}
    sources_data = data.get("sources", {})
    for src_id, src_val in sources_data.items():
        sel_data = src_val.get("selection", {})
        bud_data = src_val.get("budget", {})
        dr_data = src_val.get("date_range", {})

        sel_cfg = SelectionConfig(
            include_sections=sel_data.get("include_sections", []),
            exclude_sections=sel_data.get("exclude_sections", []),
            allowed_document_types=sel_data.get("allowed_document_types", []),
        )

        bud_cfg = SourceBudgetConfig(
            target_raw_bytes=bud_data.get("target_raw_bytes", 5368709120),
            daily_raw_bytes=bud_data.get("daily_raw_bytes", 536870912),
            daily_documents=bud_data.get("daily_documents", 1000),
            discovery_pages_per_run=bud_data.get("discovery_pages_per_run", 50),
            new_urls_per_run=bud_data.get("new_urls_per_run", 1000),
        )

        sources_dict[src_id] = HarvestSourceConfig(
            enabled=src_val.get("enabled", True),
            adapter=src_val.get("adapter", src_id),
            source_id=src_id,
            date_from=dr_data.get("from") if isinstance(dr_data, dict) else None,
            date_to=dr_data.get("to") if isinstance(dr_data, dict) else None,
            selection=sel_cfg,
            budget=bud_cfg,
        )

    return HarvestConfig(
        enabled=harvest_data.get("enabled", True),
        target=target_cfg,
        runner=runner_cfg,
        review=review_cfg,
        sources=sources_dict,
    )
