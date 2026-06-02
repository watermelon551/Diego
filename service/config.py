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
    asset_timeout_sec: float = 200.0
    asset_max_retries: int = 2
    generation_engine: str = "agentic_v2"
    debug_keep_previews: bool = False
    max_slide_repair_rounds: int = 4
    outline_timeout_retries: int = 3
    outline_timeout_backoff_sec: float = 10.0
    outline_structured_output: bool = True
    outline_critique_enabled: bool = True
    pptd_fast_requirements_enabled: bool = False
    llm_request_concurrency: int = 6
    slide_candidate_workers: int = 3
    llm_timeout_jitter_sec: float = 2.0
    llm_sanitize_think_tags: bool = True
    llm_json_repair_retry: int = 1
    slide_fatal_early_stop_rounds: int = 2
    run_max_llm_calls: int = 0
    keep_failed_candidate_js: bool = True
    slide_auto_canonicalize: bool = True
    slide_diag_max_js_lines: int = 260
    slide_diag_max_stderr_chars: int = 12000
    preview_qa_concurrency: int = 4
    asset_fetch_concurrency: int = 2
    llm_concurrency_build: int = 3
    llm_concurrency_evaluate: int = 2
    llm_concurrency_repair: int = 1
    timeout_streak_degrade_threshold: int = 3
    timeout_streak_recover_window_sec: float = 1200.0
    slide_generation_timeout_sec: float = 9000.0
    qa_finalize_timeout_sec: float = 3000.0
    compile_provider: str = "none"
    pptd_skill_dir: str = ""
    pptd_runner_mode: str = "docker"
    pptd_runner_image: str = "debian:bookworm-slim"
    pptd_runner_platform: str = "linux/amd64"
    pptd_runner_timeout_sec: float = 1200.0
    pptd_screenshot_enabled: bool = False
    pptd_screenshot_dpi: int = 150
    pagevra_base_url: str = ""
    pagevra_preview_enabled: bool = False
    pagevra_preview_timeout_sec: float = 300.0
    pagevra_compile_timeout_sec: float = 1800.0
    stratumind_base_url: str = ""
    stratumind_timeout_sec: float = 120.0
    rag_top_k: int = 10
    rag_context_max_snippets: int = 10
    rag_context_max_chars: int = 700
    run_store: str = "memory"
    database_url: str = ""
    recovery_scan_on_boot: bool = True
    event_poll_interval_sec: float = 5.0


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
    if generation_engine != "agentic_v2":
        raise ValueError(f"invalid GENERATION_ENGINE={generation_engine!r}")
    compile_provider = os.getenv("COMPILE_PROVIDER", "none").strip().lower()
    if compile_provider not in {"none", "local", "pagevra", "pptd"}:
        raise ValueError(f"invalid COMPILE_PROVIDER={compile_provider!r}")
    pptd_runner_timeout_sec = _env_float("PPTD_RUNNER_TIMEOUT_SEC", 1200.0)
    if pptd_runner_timeout_sec <= 0:
        raise ValueError("PPTD_RUNNER_TIMEOUT_SEC must be > 0")
    pptd_screenshot_dpi = _env_int("PPTD_SCREENSHOT_DPI", 150)
    pptd_runner_mode = os.getenv("PPTD_RUNNER_MODE", "docker").strip().lower()
    if pptd_runner_mode not in {"docker", "local"}:
        raise ValueError(f"invalid PPTD_RUNNER_MODE={pptd_runner_mode!r}")
    pagevra_compile_timeout_sec = _env_float("PAGEVRA_COMPILE_TIMEOUT_SEC", 1800.0)
    if pagevra_compile_timeout_sec <= 0:
        raise ValueError("PAGEVRA_COMPILE_TIMEOUT_SEC must be > 0")
    pagevra_preview_timeout_sec = _env_float("PAGEVRA_PREVIEW_TIMEOUT_SEC", 300.0)
    if pagevra_preview_timeout_sec <= 0:
        raise ValueError("PAGEVRA_PREVIEW_TIMEOUT_SEC must be > 0")
    stratumind_timeout_sec = _env_float("STRATUMIND_TIMEOUT_SECONDS", 120.0)
    if stratumind_timeout_sec <= 0:
        raise ValueError("STRATUMIND_TIMEOUT_SECONDS must be > 0")

    outline_timeout_backoff_sec = _env_float("OUTLINE_TIMEOUT_BACKOFF_SEC", 10.0)
    if outline_timeout_backoff_sec < 0:
        raise ValueError("OUTLINE_TIMEOUT_BACKOFF_SEC must be >= 0")
    llm_timeout_jitter_sec = _env_float("LLM_TIMEOUT_JITTER_SEC", 2.0)
    if llm_timeout_jitter_sec < 0:
        raise ValueError("LLM_TIMEOUT_JITTER_SEC must be >= 0")
    timeout_streak_recover_window_sec = _env_float("TIMEOUT_STREAK_RECOVER_WINDOW_SEC", 1200.0)
    if timeout_streak_recover_window_sec < 0:
        raise ValueError("TIMEOUT_STREAK_RECOVER_WINDOW_SEC must be >= 0")
    qa_finalize_timeout_sec = _env_float("QA_FINALIZE_TIMEOUT_SEC", 3000.0)
    if qa_finalize_timeout_sec <= 0:
        raise ValueError("QA_FINALIZE_TIMEOUT_SEC must be > 0")
    slide_generation_timeout_sec = _env_float("DIEGO_SLIDE_GENERATION_TIMEOUT_SEC", 9000.0)
    if slide_generation_timeout_sec < 3000:
        raise ValueError("DIEGO_SLIDE_GENERATION_TIMEOUT_SEC must be >= 3000")
    run_store = os.getenv("DIEGO_RUN_STORE", "memory").strip().lower()
    if run_store not in {"memory", "postgres"}:
        raise ValueError(f"invalid DIEGO_RUN_STORE={run_store!r}")
    database_url = os.getenv("DIEGO_DATABASE_URL", "").strip()
    if run_store == "postgres" and not database_url:
        raise ValueError("DIEGO_DATABASE_URL is required when DIEGO_RUN_STORE=postgres")
    event_poll_interval_sec = _env_float("DIEGO_EVENT_POLL_INTERVAL_SEC", 0.5)
    if event_poll_interval_sec <= 0:
        raise ValueError("DIEGO_EVENT_POLL_INTERVAL_SEC must be > 0")

    return Settings(
        llm_api_style=os.getenv("LLM_API_STYLE", "openai_chat").strip().lower(),
        llm_base_url=_require_env("LLM_BASE_URL"),
        llm_api_key=_require_env("LLM_API_KEY"),
        llm_model=_require_env("LLM_MODEL"),
        llm_timeout_sec=_env_float("LLM_TIMEOUT_SEC", 3000.0),
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
        asset_timeout_sec=_env_float("ASSET_TIMEOUT_SEC", 200.0),
        asset_max_retries=_env_int("ASSET_MAX_RETRIES", 2),
        generation_engine=generation_engine,
        debug_keep_previews=_env_bool("DEBUG_KEEP_PREVIEWS", False),
        max_slide_repair_rounds=_env_int("MAX_SLIDE_REPAIR_ROUNDS", 4),
        outline_timeout_retries=_env_int("OUTLINE_TIMEOUT_RETRIES", 3, min_value=0),
        outline_timeout_backoff_sec=outline_timeout_backoff_sec,
        outline_structured_output=_env_bool("OUTLINE_STRUCTURED_OUTPUT", True),
        outline_critique_enabled=_env_bool("OUTLINE_CRITIQUE_ENABLED", True),
        pptd_fast_requirements_enabled=_env_bool(
            "PPTD_FAST_REQUIREMENTS_ENABLED", True
        ),
        llm_request_concurrency=_env_int("LLM_REQUEST_CONCURRENCY", 6),
        slide_candidate_workers=_env_int("SLIDE_CANDIDATE_WORKERS", 3),
        llm_timeout_jitter_sec=llm_timeout_jitter_sec,
        llm_sanitize_think_tags=_env_bool("LLM_SANITIZE_THINK_TAGS", True),
        llm_json_repair_retry=_env_int("LLM_JSON_REPAIR_RETRY", 1, min_value=0),
        slide_fatal_early_stop_rounds=_env_int("SLIDE_FATAL_EARLY_STOP_ROUNDS", 2),
        run_max_llm_calls=_env_int("RUN_MAX_LLM_CALLS", 0, min_value=0),
        keep_failed_candidate_js=_env_bool("KEEP_FAILED_CANDIDATE_JS", True),
        slide_auto_canonicalize=_env_bool("SLIDE_AUTO_CANONICALIZE", True),
        slide_diag_max_js_lines=_env_int("SLIDE_DIAG_MAX_JS_LINES", 260),
        slide_diag_max_stderr_chars=_env_int("SLIDE_DIAG_MAX_STDERR_CHARS", 12000),
        preview_qa_concurrency=_env_int("PREVIEW_QA_CONCURRENCY", 4),
        asset_fetch_concurrency=_env_int("ASSET_FETCH_CONCURRENCY", 2),
        llm_concurrency_build=_env_int("LLM_CONCURRENCY_BUILD", 3),
        llm_concurrency_evaluate=_env_int("LLM_CONCURRENCY_EVALUATE", 2),
        llm_concurrency_repair=_env_int("LLM_CONCURRENCY_REPAIR", 1),
        timeout_streak_degrade_threshold=_env_int("TIMEOUT_STREAK_DEGRADE_THRESHOLD", 3),
        timeout_streak_recover_window_sec=timeout_streak_recover_window_sec,
        slide_generation_timeout_sec=slide_generation_timeout_sec,
        qa_finalize_timeout_sec=qa_finalize_timeout_sec,
        compile_provider=compile_provider,
        pptd_skill_dir=os.getenv("PPTD_SKILL_DIR", "").strip(),
        pptd_runner_mode=pptd_runner_mode,
        pptd_runner_image=os.getenv("PPTD_RUNNER_IMAGE", "debian:bookworm-slim").strip(),
        pptd_runner_platform=os.getenv("PPTD_RUNNER_PLATFORM", "linux/amd64").strip(),
        pptd_runner_timeout_sec=pptd_runner_timeout_sec,
        pptd_screenshot_enabled=_env_bool("PPTD_SCREENSHOT_ENABLED", False),
        pptd_screenshot_dpi=pptd_screenshot_dpi,
        pagevra_base_url=os.getenv("PAGEVRA_BASE_URL", "").strip().rstrip("/"),
        pagevra_preview_enabled=_env_bool("PAGEVRA_PREVIEW_ENABLED", False),
        pagevra_preview_timeout_sec=pagevra_preview_timeout_sec,
        pagevra_compile_timeout_sec=pagevra_compile_timeout_sec,
        stratumind_base_url=os.getenv("STRATUMIND_BASE_URL", "").strip().rstrip("/"),
        stratumind_timeout_sec=stratumind_timeout_sec,
        rag_top_k=_env_int("DIEGO_RAG_TOP_K", 10),
        rag_context_max_snippets=_env_int("DIEGO_RAG_CONTEXT_MAX_SNIPPETS", 10),
        rag_context_max_chars=_env_int("DIEGO_RAG_CONTEXT_MAX_CHARS", 700),
        run_store=run_store,
        database_url=database_url,
        recovery_scan_on_boot=_env_bool("DIEGO_RECOVERY_SCAN_ON_BOOT", True),
        event_poll_interval_sec=event_poll_interval_sec,
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
