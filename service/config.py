from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_sec: float
    llm_max_retries: int
    llm_temperature_outline: float
    llm_temperature_slide: float
    slide_concurrency: int
    slide_retry: int


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


def load_settings(env_file: str | Path = ".env") -> Settings:
    _load_env_file(env_file)
    return Settings(
        llm_base_url=_require_env("LLM_BASE_URL"),
        llm_api_key=_require_env("LLM_API_KEY"),
        llm_model=_require_env("LLM_MODEL"),
        llm_timeout_sec=_env_float("LLM_TIMEOUT_SEC", 60.0),
        llm_max_retries=_env_int("LLM_MAX_RETRIES", 2),
        llm_temperature_outline=_env_float("LLM_TEMPERATURE_OUTLINE", 0.3),
        llm_temperature_slide=_env_float("LLM_TEMPERATURE_SLIDE", 0.6),
        slide_concurrency=_env_int("SLIDE_CONCURRENCY", 4),
        slide_retry=_env_int("SLIDE_RETRY", 2),
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
