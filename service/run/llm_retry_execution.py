from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

from ..llm import LLMTimeoutError
from ..models import EventType


async def call_llm_with_timeout_retry(
    *,
    run_id: str,
    phase: str,
    action: Callable[[], Awaitable[Any]],
    outline_timeout_retries: int,
    llm_timeout_sec: float,
    llm_timeout_jitter_sec: float,
    outline_timeout_backoff_sec: float,
    llm_request_gate: Any,
    llm_pressure_gate: Any,
    phase_gate: Any,
    publish: Callable[[str, EventType, dict[str, Any]], Awaitable[None]],
    consume_run_llm_budget: Callable[[str, str], None],
    is_under_timeout_pressure: Callable[[], bool],
    note_llm_success: Callable[[], None],
    is_retryable_llm_exception: Callable[[Exception], bool],
    note_timeout: Callable[[], None],
    exception_reason: Callable[[Exception], str],
    retry_after_seconds: Callable[[Exception], float | None],
) -> Any:
    max_attempts = outline_timeout_retries + 1
    gate_timeout_sec = max(300.0, float(llm_timeout_sec) + 5.0)
    for attempt in range(1, max_attempts + 1):
        acquired_global = False
        acquired_phase = False
        acquired_pressure = False
        try:
            consume_run_llm_budget(run_id, phase)
            acquired_global = await asyncio.to_thread(llm_request_gate.acquire, True, gate_timeout_sec)
            if not acquired_global:
                raise TimeoutError("llm request concurrency gate timeout")
            acquired_phase = await asyncio.to_thread(phase_gate.acquire, True, gate_timeout_sec)
            if not acquired_phase:
                raise TimeoutError("llm phase concurrency gate timeout")
            if is_under_timeout_pressure():
                acquired_pressure = await asyncio.to_thread(llm_pressure_gate.acquire, True, gate_timeout_sec)
                if not acquired_pressure:
                    raise TimeoutError("llm pressure gate timeout")
            result = await action()
            note_llm_success()
            return result
        except Exception as exc:
            if not is_retryable_llm_exception(exc):
                raise
            note_timeout()
            reason = exception_reason(exc)
            await publish(
                run_id,
                EventType.LLM_REQUEST_TIMEOUT,
                {"phase": phase, "attempt": attempt, "max_attempts": max_attempts, "reason": reason},
            )
            if attempt >= max_attempts:
                raise LLMTimeoutError(attempts=attempt, reason=reason, phase=phase) from exc
            jitter = random.uniform(0.0, llm_timeout_jitter_sec) if llm_timeout_jitter_sec > 0 else 0.0
            delay = outline_timeout_backoff_sec * (2 ** (attempt - 1)) + jitter
            retry_after = retry_after_seconds(exc)
            if retry_after is not None:
                delay = max(delay, retry_after)
            await publish(
                run_id,
                EventType.LLM_REQUEST_RETRY,
                {
                    "phase": phase,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "next_delay_sec": round(delay, 2),
                    "reason": reason,
                },
            )
            if delay > 0:
                await asyncio.sleep(delay)
        finally:
            if acquired_pressure:
                llm_pressure_gate.release()
            if acquired_phase:
                phase_gate.release()
            if acquired_global:
                llm_request_gate.release()
    raise RuntimeError("unreachable timeout retry loop")
