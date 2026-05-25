from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ...models import EventType, GenerationMode, RunRecord, RunStatus


class ScratchCompileMixin:
    async def _mark_compile_started(self, *, run_id: str) -> str:
        orch = self.orch
        await orch.store.update_run(
            run_id, lambda r: setattr(r, "status", RunStatus.COMPILING)
        )
        requested_provider = str(
            getattr(orch.settings, "compile_provider", "none") or "none"
        )
        await orch.store.update_run(
            run_id,
            lambda r: setattr(r, "compile_requested_provider", requested_provider),
        )
        await orch._publish(
            run_id,
            EventType.COMPILE_STARTED,
            {"requested_provider": requested_provider},
        )
        return requested_provider

    async def _compile_scratch_run(
        self,
        *,
        run_id: str,
        run: RunRecord,
        design: Any,
        requested_provider: str,
    ) -> None:
        orch = self.orch
        slides_dir = Path(run.artifact_dir) / "slides"
        compile_start = time.perf_counter()
        sorted_slides = sorted(run.slides, key=lambda x: x.slide_no)
        compile_result = await orch.compile_engine.compile_scratch_run(
            run_id=run_id,
            slides_dir=slides_dir,
            slide_count=len(sorted_slides),
            theme=design.theme,
        )
        if compile_result.deferred:
            await self._apply_deferred_compile_result(
                run_id=run_id,
                compile_result=compile_result,
                requested_provider=requested_provider,
                compile_start=compile_start,
            )
            return
        if not compile_result["ok"]:
            await orch._fail_run(
                run_id,
                "COMPILING",
                "COMPILE_SCRIPT_FAILED",
                retryable=True,
                error_details={
                    "return_code": compile_result["return_code"],
                    "reason": compile_result["reason"],
                    "provider": compile_result.get("provider"),
                    "requested_provider": compile_result.get(
                        "requested_provider", requested_provider
                    ),
                    "fallback_used": bool(compile_result.get("fallback_used")),
                    "fallback_from": compile_result.get("fallback_from"),
                    "details": compile_result.get("error_details") or {},
                },
            )
            return

        pptx_path = compile_result["pptx_path"]

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = str(compile_result["compile_js_path"])
            r.pptx_path = str(pptx_path)
            r.compile_requested_provider = str(
                compile_result.get("requested_provider") or requested_provider
            )
            r.compile_provider = str(compile_result.get("provider") or "")
            r.compile_status = "succeeded"
            r.compile_bundle_ready = True
            r.compile_fallback_used = bool(compile_result.get("fallback_used"))
            r.compile_error_code = None
            r.compile_error_details = {}
            r.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            r.render_version += 1

        await orch.store.update_run(run_id, apply_compile)
        await orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(pptx_path),
                "provider": compile_result.get("provider", "local"),
                "requested_provider": compile_result.get(
                    "requested_provider", requested_provider
                ),
                "fallback_used": bool(compile_result.get("fallback_used")),
                "fallback_from": compile_result.get("fallback_from"),
            },
        )
        await orch.finalize_quality_stage.execute(
            run_id=run_id,
            mode=GenerationMode.SCRATCH,
            design=design,
            from_stage="COMPILING",
            success_reason="scratch compile+qa completed",
        )

    async def _apply_deferred_compile_result(
        self,
        *,
        run_id: str,
        compile_result: Any,
        requested_provider: str,
        compile_start: float,
    ) -> None:
        orch = self.orch

        def apply_deferred_compile(r: RunRecord) -> None:
            r.compile_js_path = str(compile_result["compile_js_path"])
            r.compile_requested_provider = str(
                compile_result.get("requested_provider") or requested_provider
            )
            r.compile_provider = None
            r.compile_status = "bundle_ready"
            r.compile_bundle_ready = bool(compile_result.bundle_ready)
            r.compile_fallback_used = False
            r.compile_error_code = None
            r.compile_error_details = {}
            r.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            r.render_version += 1
            previous = (
                r.qa_report
                if isinstance(getattr(r, "qa_report", None), dict)
                else {}
            )
            r.qa_report = {
                **previous,
                "passed": True,
                "degraded": True,
                "degraded_reason": "EXTERNAL_COMPILE_DEFERRED",
                "mode": GenerationMode.SCRATCH.value,
            }

        await orch.store.update_run(run_id, apply_deferred_compile)
        await orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": "",
                "provider": "none",
                "requested_provider": compile_result.get(
                    "requested_provider", requested_provider
                ),
                "bundle_ready": bool(compile_result.bundle_ready),
                "deferred": True,
                "reason": compile_result.reason,
            },
        )
        await orch._publish(
            run_id,
            EventType.QA_COMPLETED,
            {
                "passed": True,
                "degraded": True,
                "degraded_reason": "EXTERNAL_COMPILE_DEFERRED",
                "mode": GenerationMode.SCRATCH.value,
            },
        )
        await orch._publish(
            run_id,
            EventType.SLIDE_PREVIEW_QA,
            {
                "mode": GenerationMode.SCRATCH.value,
                "status": "skipped",
                "reason": "external_compile_deferred",
            },
        )
        await orch._finalize_run_success(
            run_id,
            from_stage="COMPILING",
            reason="generation completed; external compile deferred",
        )
