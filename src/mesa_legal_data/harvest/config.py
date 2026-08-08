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

    if target_cfg.raw_bytes <= 0:
        raise ValueError(f"CONFIG_INVALID_TARGET_RAW_BYTES: target.raw_bytes must be > 0, got: {target_cfg.raw_bytes}")
    if target_cfg.minimum_free_disk_bytes <= 0:
        raise ValueError(
            f"CONFIG_INVALID_MIN_FREE_DISK: minimum_free_disk_bytes must be > 0, got: {target_cfg.minimum_free_disk_bytes}"
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

    if not runner_cfg.pipeline_after_download:
        raise ValueError(
            "CONFIG_UNSUPPORTED_PIPELINE_AFTER_DOWNLOAD: pipeline_after_download=false is not supported for MVP; must be set to true"
        )
    if runner_cfg.worker_count != 1:
        raise ValueError(
            f"CONFIG_UNSUPPORTED_WORKER_COUNT: Multi-worker orchestrator is not supported in this MVP. worker_count must be 1, got: {runner_cfg.worker_count}"
        )
    if runner_cfg.batch_size < 1:
        raise ValueError(f"CONFIG_INVALID_BATCH_SIZE: batch_size must be >= 1, got: {runner_cfg.batch_size}")
    if runner_cfg.lease_seconds <= 0:
        raise ValueError(f"CONFIG_INVALID_LEASE_SECONDS: lease_seconds must be > 0, got: {runner_cfg.lease_seconds}")
    if runner_cfg.max_runtime_seconds <= 0:
        raise ValueError(
            f"CONFIG_INVALID_MAX_RUNTIME: max_runtime_seconds must be > 0, got: {runner_cfg.max_runtime_seconds}"
        )
    if runner_cfg.max_attempts < 1:
        raise ValueError(f"CONFIG_INVALID_MAX_ATTEMPTS: max_attempts must be >= 1, got: {runner_cfg.max_attempts}")
    if not (0 < runner_cfg.stop_on_error_rate <= 1.0):
        raise ValueError(
            f"CONFIG_INVALID_ERROR_RATE: stop_on_error_rate must be between 0 and 1, got: {runner_cfg.stop_on_error_rate}"
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

        if bud_cfg.daily_documents < 1:
            raise ValueError(f"CONFIG_INVALID_DAILY_DOCUMENTS: daily_documents must be >= 1 for {src_id}")
        if bud_cfg.daily_raw_bytes <= 0:
            raise ValueError(f"CONFIG_INVALID_DAILY_RAW_BYTES: daily_raw_bytes must be > 0 for {src_id}")
        if bud_cfg.target_raw_bytes <= 0:
            raise ValueError(f"CONFIG_INVALID_SOURCE_TARGET_RAW: target_raw_bytes must be > 0 for {src_id}")
        if bud_cfg.discovery_pages_per_run < 1:
            raise ValueError(f"CONFIG_INVALID_DISCOVERY_PAGES: discovery_pages_per_run must be >= 1 for {src_id}")
        if bud_cfg.new_urls_per_run < 1:
            raise ValueError(f"CONFIG_INVALID_NEW_URLS: new_urls_per_run must be >= 1 for {src_id}")

        date_from_val = dr_data.get("from") if isinstance(dr_data, dict) else None
        date_to_val = dr_data.get("to") if isinstance(dr_data, dict) else None
        if date_from_val and date_to_val and date_from_val > date_to_val:
            raise ValueError(
                f"CONFIG_INVALID_DATE_RANGE: date_from ({date_from_val}) cannot be after date_to ({date_to_val}) for {src_id}"
            )

        sources_dict[src_id] = HarvestSourceConfig(
            enabled=src_val.get("enabled", True),
            adapter=src_val.get("adapter", src_id),
            source_id=src_id,
            date_from=date_from_val,
            date_to=date_to_val,
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
