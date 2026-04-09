from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    llm_api_style: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_sec: float
    llm_max_retries: int
    llm_temperature_outline: float
    llm_temperature_slide: float
    slide_concurrency: int
    slide_retry: int
    qa_enabled: bool
    repair_rounds: int
    asset_provider: str = "auto"
    unsplash_access_key: str = ""
    pexels_api_key: str = ""
    asset_timeout_sec: float = 20.0
    asset_max_retries: int = 2
    generation_engine: str = "agentic_v2"
    debug_keep_previews: bool = False
    max_slide_repair_rounds: int = 4


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"missing required environment variable: {name}")
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"invalid float env {name}={raw!r}") from exc


def _env_int(name: str, default: int, min_value: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid int env {name}={raw!r}") from exc
    if value < min_value:
        raise ValueError(f"env {name} must be >= {min_value}, got {value}")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def load_settings(env_file: str | Path = ".env") -> Settings:
    _load_env_file(env_file)
    asset_provider = os.getenv("ASSET_PROVIDER", "auto").strip().lower()
    generation_engine = os.getenv("GENERATION_ENGINE", "agentic_v2").strip().lower()
    unsplash_access_key = os.getenv("UNSPLASH_ACCESS_KEY", "").strip()
    pexels_api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if asset_provider not in {"mock", "none", "auto", "unsplash", "pexels"}:
        raise ValueError(f"invalid ASSET_PROVIDER={asset_provider!r}")
    if asset_provider == "unsplash" and not unsplash_access_key:
        raise ValueError("UNSPLASH_ACCESS_KEY is required when ASSET_PROVIDER=unsplash")
    if asset_provider == "pexels" and not pexels_api_key:
        raise ValueError("PEXELS_API_KEY is required when ASSET_PROVIDER=pexels")
    if asset_provider == "auto" and not (unsplash_access_key or pexels_api_key):
        raise ValueError("UNSPLASH_ACCESS_KEY or PEXELS_API_KEY is required when ASSET_PROVIDER=auto")
    if generation_engine not in {"agentic_v2", "legacy"}:
        raise ValueError(f"invalid GENERATION_ENGINE={generation_engine!r}")
    return Settings(
        llm_api_style=os.getenv("LLM_API_STYLE", "openai_chat").strip().lower(),
        llm_base_url=_require_env("LLM_BASE_URL"),
        llm_api_key=_require_env("LLM_API_KEY"),
        llm_model=_require_env("LLM_MODEL"),
        llm_timeout_sec=_env_float("LLM_TIMEOUT_SEC", 60.0),
        llm_max_retries=_env_int("LLM_MAX_RETRIES", 2),
        llm_temperature_outline=_env_float("LLM_TEMPERATURE_OUTLINE", 0.3),
        llm_temperature_slide=_env_float("LLM_TEMPERATURE_SLIDE", 0.6),
        slide_concurrency=_env_int("SLIDE_CONCURRENCY", 4),
        slide_retry=_env_int("SLIDE_RETRY", 2),
        qa_enabled=_env_bool("QA_ENABLED", True),
        repair_rounds=_env_int("REPAIR_ROUNDS", 2),
        asset_provider=asset_provider,
        unsplash_access_key=unsplash_access_key,
        pexels_api_key=pexels_api_key,
        asset_timeout_sec=_env_float("ASSET_TIMEOUT_SEC", 20.0),
        asset_max_retries=_env_int("ASSET_MAX_RETRIES", 2),
        generation_engine=generation_engine,
        debug_keep_previews=_env_bool("DEBUG_KEEP_PREVIEWS", False),
        max_slide_repair_rounds=_env_int("MAX_SLIDE_REPAIR_ROUNDS", 4),
    )


def _load_env_file(env_file: str | Path) -> None:
    path = Path(env_file)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
