from __future__ import annotations

import threading
from typing import Any

from .llm_retry_execution import call_llm_with_timeout_retry
from .llm_runtime_control import (
    clear_run_llm_budget,
    consume_run_llm_budget,
    exception_reason,
    init_run_llm_budget,
    is_retryable_http_status_error,
    is_retryable_llm_exception,
    is_timeout_failure_payload,
    is_under_timeout_pressure,
    llm_phase_bucket,
    llm_phase_gate,
    note_llm_success,
    note_timeout,
    recommended_candidate_workers,
    retry_after_seconds,
    retryable_http_statuses,
)


class RunLlmRuntimeMixin:
    def _retryable_http_statuses(self) -> set[int]:
        return retryable_http_statuses()

    def _is_retryable_http_status_error(self, exc: Exception) -> bool:
        return is_retryable_http_status_error(exc)

    def _retry_after_seconds(self, exc: Exception) -> float | None:
        return retry_after_seconds(exc)

    def _is_retryable_llm_exception(self, exc: Exception) -> bool:
        return is_retryable_llm_exception(exc)

    def _llm_phase_bucket(self, phase: str) -> str:
        return llm_phase_bucket(phase)

    def _llm_phase_gate(self, phase: str) -> threading.BoundedSemaphore:
        return llm_phase_gate(
            phase=phase,
            build_gate=self._llm_phase_build_gate,
            repair_gate=self._llm_phase_repair_gate,
            evaluate_gate=self._llm_phase_evaluate_gate,
        )

    def _is_under_timeout_pressure(self) -> bool:
        return is_under_timeout_pressure(
            timeout_lock=self._timeout_lock,
            timeout_streak=self._timeout_streak,
            last_timeout_monotonic=self._last_timeout_monotonic,
            degrade_threshold=self.timeout_streak_degrade_threshold,
            recover_window_sec=self.timeout_streak_recover_window_sec,
        )

    def _note_timeout(self) -> None:
        self._timeout_streak, self._last_timeout_monotonic = note_timeout(
            timeout_lock=self._timeout_lock,
            timeout_streak=self._timeout_streak,
        )

    def _note_llm_success(self) -> None:
        self._timeout_streak = note_llm_success(
            timeout_lock=self._timeout_lock,
            timeout_streak=self._timeout_streak,
        )

    def _recommended_candidate_workers(self) -> int:
        return recommended_candidate_workers(
            slide_candidate_workers=self.slide_candidate_workers,
            timeout_lock=self._timeout_lock,
            timeout_streak=self._timeout_streak,
        )

    def _init_run_llm_budget(self, *, run_id: str, target_slide_count: int) -> None:
        init_run_llm_budget(
            run_id=run_id,
            target_slide_count=target_slide_count,
            max_slide_repair_rounds=self.max_slide_repair_rounds,
            run_max_llm_calls=self.run_max_llm_calls,
            run_budget_lock=self._run_budget_lock,
            run_llm_call_counts=self._run_llm_call_counts,
            run_llm_call_limits=self._run_llm_call_limits,
        )

    def _clear_run_llm_budget(self, run_id: str) -> None:
        clear_run_llm_budget(
            run_id=run_id,
            run_budget_lock=self._run_budget_lock,
            run_llm_call_counts=self._run_llm_call_counts,
            run_llm_call_limits=self._run_llm_call_limits,
            run_asset_keys=self._run_asset_keys,
        )

    def _consume_run_llm_budget(self, *, run_id: str, phase: str) -> None:
        consume_run_llm_budget(
            run_id=run_id,
            phase=phase,
            run_budget_lock=self._run_budget_lock,
            run_llm_call_counts=self._run_llm_call_counts,
            run_llm_call_limits=self._run_llm_call_limits,
        )

    def _is_timeout_failure_payload(self, payload: dict[str, Any]) -> bool:
        return is_timeout_failure_payload(payload)

    def _exception_reason(self, exc: Exception) -> str:
        return exception_reason(exc)

    async def _call_llm_with_timeout_retry(
        self,
        *,
        run_id: str,
        phase: str,
        action: Any,
    ) -> Any:
        return await call_llm_with_timeout_retry(
            run_id=run_id,
            phase=phase,
            action=action,
            outline_timeout_retries=self.outline_timeout_retries,
            llm_timeout_sec=self.settings.llm_timeout_sec,
            llm_timeout_jitter_sec=self.llm_timeout_jitter_sec,
            outline_timeout_backoff_sec=self.outline_timeout_backoff_sec,
            llm_request_gate=self._llm_request_gate,
            llm_pressure_gate=self._llm_pressure_gate,
            phase_gate=self._llm_phase_gate(phase),
            publish=self._publish,
            consume_run_llm_budget=lambda current_run_id, current_phase: self._consume_run_llm_budget(
                run_id=current_run_id,
                phase=current_phase,
            ),
            is_under_timeout_pressure=self._is_under_timeout_pressure,
            note_llm_success=self._note_llm_success,
            is_retryable_llm_exception=self._is_retryable_llm_exception,
            note_timeout=self._note_timeout,
            exception_reason=self._exception_reason,
            retry_after_seconds=self._retry_after_seconds,
        )

    async def _call_outline_with_timeout_retry(
        self,
        *,
        run_id: str,
        phase: str,
        action: Any,
    ) -> Any:
        return await self._call_llm_with_timeout_retry(
            run_id=run_id,
            phase=phase,
            action=action,
        )
