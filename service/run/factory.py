from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import load_settings
from ..infra.store import PostgresRunStore, RunStore
from ..llm import OpenAICompatibleLLMClient
from .orchestrator import RunOrchestrator


def build_orchestrator(base_dir: Path) -> RunOrchestrator:
    settings = load_settings()
    artifacts_dir = base_dir / "artifacts"
    templates_dir = base_dir / "templates"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)
    llm_client = OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        api_style=settings.llm_api_style,
        timeout_sec=settings.llm_timeout_sec,
        outline_temperature=settings.llm_temperature_outline,
        slide_temperature=settings.llm_temperature_slide,
        outline_structured_output=settings.outline_structured_output,
        sanitize_think_tags=settings.llm_sanitize_think_tags,
        json_repair_retry=settings.llm_json_repair_retry,
    )
    resolved_store: Any
    if settings.run_store == "postgres":
        resolved_store = PostgresRunStore(
            base_dir=base_dir,
            database_url=settings.database_url,
            event_poll_interval_sec=settings.event_poll_interval_sec,
        )
    else:
        resolved_store = RunStore(base_dir=base_dir)

    return RunOrchestrator(
        store=resolved_store,
        artifacts_base=artifacts_dir,
        templates_base=templates_dir,
        llm_client=llm_client,
        settings=settings,
    )
