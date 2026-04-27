from __future__ import annotations

import threading
import time

import httpx

from ..llm import LLMEmptyResponseError, LLMTimeoutError


def retryable_http_statuses() -> set[int]:
    return {
        408,
        409,
        425,
        429,
        500,
        502,
        503,
        504,
        520,
        521,
        522,
        523,
        524,
        529,
    }


def is_retryable_http_status_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    try:
        code = int(exc.response.status_code)
    except Exception:
        return False
    return code in retryable_http_statuses()


def retry_after_seconds(exc: Exception) -> float | None:
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    header = (exc.response.headers.get("Retry-After") or "").strip()
    if not header:
        return None
    try:
        value = float(header)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def is_retryable_llm_exception(exc: Exception) -> bool:
    if isinstance(exc, (LLMTimeoutError, httpx.TimeoutException, TimeoutError)):
        return True
    if isinstance(exc, LLMEmptyResponseError):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    return is_retryable_http_status_error(exc)


def llm_phase_bucket(phase: str) -> str:
    lowered = str(phase or "").lower()
    if any(token in lowered for token in (".repair", "repair", ".revise", "polish")):
        return "repair"
    if any(token in lowered for token in (".evaluate", ".review", "critic", "quality", "qa")):
        return "evaluate"
    return "build"


def llm_phase_gate(
    *,
    phase: str,
    build_gate: threading.BoundedSemaphore,
    repair_gate: threading.BoundedSemaphore,
    evaluate_gate: threading.BoundedSemaphore,
) -> threading.BoundedSemaphore:
    bucket = llm_phase_bucket(phase)
    if bucket == "repair":
        return repair_gate
    if bucket == "evaluate":
        return evaluate_gate
    return build_gate


def is_under_timeout_pressure(
    *,
    timeout_lock: threading.Lock,
    timeout_streak: int,
    last_timeout_monotonic: float,
    degrade_threshold: int,
    recover_window_sec: float,
) -> bool:
    with timeout_lock:
        streak = timeout_streak
        last_timeout = last_timeout_monotonic
    if streak < degrade_threshold:
        return False
    if recover_window_sec <= 0:
        return True
    return (time.monotonic() - last_timeout) <= recover_window_sec


def note_timeout(*, timeout_lock: threading.Lock, timeout_streak: int) -> tuple[int, float]:
    with timeout_lock:
        next_streak = min(100, timeout_streak + 1)
        timestamp = time.monotonic()
    return next_streak, timestamp


def note_llm_success(*, timeout_lock: threading.Lock, timeout_streak: int) -> int:
    with timeout_lock:
        if timeout_streak > 0:
            return timeout_streak - 1
    return timeout_streak


def recommended_candidate_workers(*, slide_candidate_workers: int, timeout_lock: threading.Lock, timeout_streak: int) -> int:
    base = max(1, slide_candidate_workers)
    with timeout_lock:
        streak = timeout_streak
    if streak >= 8:
        return 1
    if streak >= 4:
        return min(base, 2)
    return base


def init_run_llm_budget(
    *,
    run_id: str,
    target_slide_count: int,
    max_slide_repair_rounds: int,
    run_max_llm_calls: int,
    run_budget_lock: threading.Lock,
    run_llm_call_counts: dict[str, int],
    run_llm_call_limits: dict[str, int],
) -> None:
    dynamic_default = max(60, int(target_slide_count) * (max(1, max_slide_repair_rounds) * 2 + 4))
    limit = run_max_llm_calls if run_max_llm_calls > 0 else dynamic_default
    with run_budget_lock:
        run_llm_call_counts[run_id] = 0
        run_llm_call_limits[run_id] = max(1, limit)


def clear_run_llm_budget(
    *,
    run_id: str,
    run_budget_lock: threading.Lock,
    run_llm_call_counts: dict[str, int],
    run_llm_call_limits: dict[str, int],
    run_asset_keys: dict[str, set[str]],
) -> None:
    with run_budget_lock:
        run_llm_call_counts.pop(run_id, None)
        run_llm_call_limits.pop(run_id, None)
        run_asset_keys.pop(run_id, None)


def consume_run_llm_budget(
    *,
    run_id: str,
    phase: str,
    run_budget_lock: threading.Lock,
    run_llm_call_counts: dict[str, int],
    run_llm_call_limits: dict[str, int],
) -> None:
    with run_budget_lock:
        limit = run_llm_call_limits.get(run_id)
        if limit is None:
            return
        next_count = run_llm_call_counts.get(run_id, 0) + 1
        run_llm_call_counts[run_id] = next_count
        if next_count > limit:
            raise RuntimeError(f"llm call budget exceeded at {phase}: {next_count}>{limit}")


def is_timeout_failure_payload(payload: dict[str, object]) -> bool:
    reason = str(payload.get("reason", "")).lower()
    error_type = str(payload.get("error_type", ""))
    if "timeout" in reason or "Timeout" in error_type:
        return True
    return any(code in reason for code in (" 429", " 500", " 502", " 503", " 504", " 529"))


def exception_reason(exc: Exception) -> str:
    reason = str(exc).strip()
    return reason or repr(exc)
