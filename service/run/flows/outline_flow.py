from __future__ import annotations

import time
import traceback
from typing import Any

from ...llm import LLMTimeoutError
from .outline_flow_errors import OutlineFlowStopped
from .outline_finalize_mixin import OutlineFinalizeMixin
from .outline_generation_mixin import OutlineGenerationMixin
from .outline_requirements_mixin import OutlineRequirementsMixin


class OutlineFlowService(
    OutlineRequirementsMixin,
    OutlineGenerationMixin,
    OutlineFinalizeMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def execute(self, run_id: str) -> None:
        orch = self.orch
        started = time.perf_counter()
        run = await orch.store.get_run(run_id)
        if run is None:
            return
        try:
            (
                rag_context_snippets,
                rag_retrieval,
                requirements_report,
                effective_template_style,
            ) = await self._prepare_outline_requirements(run_id=run_id, run=run)
            outline = await self._draft_outline(
                run_id=run_id,
                run=run,
                rag_context_snippets=rag_context_snippets,
                effective_template_style=effective_template_style,
            )
            if outline is None:
                return
            outline = await self._critique_outline(
                run_id=run_id,
                run=run,
                outline=outline,
                rag_context_snippets=rag_context_snippets,
                effective_template_style=effective_template_style,
            )
            await self._finalize_outline(
                run_id=run_id,
                run=run,
                outline=outline,
                requirements_report=requirements_report,
                rag_retrieval=rag_retrieval,
                effective_template_style=effective_template_style,
                started=started,
            )
        except OutlineFlowStopped:
            return
        except LLMTimeoutError as exc:
            await orch._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                "OUTLINE_LLM_TIMEOUT",
                retryable=True,
                error_details={
                    "phase": exc.phase,
                    "attempts": exc.attempts,
                    "reason": orch._exception_reason(exc),
                    "error_type": type(exc).__name__,
                    "provider_mode": orch.settings.llm_api_style,
                },
            )
        except Exception as exc:
            reason = str(exc).strip() or repr(exc)
            await orch._fail_run(
                run_id,
                "OUTLINE_DRAFTING",
                "OUTLINE_LLM_ERROR",
                retryable=True,
                error_details={
                    "reason": reason,
                    "error_type": type(exc).__name__,
                    "provider_mode": orch.settings.llm_api_style,
                    "traceback": traceback.format_exc(limit=4),
                },
            )
