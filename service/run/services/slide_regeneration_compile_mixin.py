from __future__ import annotations

import time
from pathlib import Path

from ...models import EventType, RunRecord, RunStatus


class SlideRegenerationCompileMixin:
    async def _finalize_scratch_regeneration_compile(
        self,
        *,
        run_id: str,
        run: RunRecord,
        design,
    ) -> None:
        orch = self.orch
        compile_start = time.perf_counter()
        compile_result = await orch.compile_engine.compile_scratch_run(
            run_id=run_id,
            slides_dir=Path(run.artifact_dir) / "slides",
            slide_count=len(run.slides),
            theme=design.theme,
        )
        if not compile_result["ok"]:
            raise RuntimeError(
                str(compile_result.get("reason") or "scratch recompile failed")
            )

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = str(compile_result["compile_js_path"])
            if compile_result.get("pptx_path") is not None:
                r.pptx_path = str(compile_result["pptx_path"])
            r.compile_requested_provider = str(
                compile_result.get("requested_provider")
                or getattr(orch.settings, "compile_provider", "none")
            )
            provider = compile_result.get("provider")
            r.compile_provider = (
                str(provider or "") if provider not in {None, "none"} else None
            )
            r.compile_status = (
                "bundle_ready"
                if bool(compile_result.get("deferred"))
                else "succeeded"
            )
            r.compile_bundle_ready = True
            r.compile_fallback_used = bool(compile_result.get("fallback_used"))
            r.compile_error_code = None
            r.compile_error_details = {}
            r.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            r.status = RunStatus.SUCCEEDED
            r.render_version += 1

        await orch.store.update_run(run_id, apply_compile)
        await orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(compile_result.get("pptx_path") or ""),
                "provider": compile_result.get("provider", "local"),
                "requested_provider": compile_result.get(
                    "requested_provider", orch.settings.compile_provider
                ),
                "fallback_used": bool(compile_result.get("fallback_used")),
                "fallback_from": compile_result.get("fallback_from"),
                "bundle_ready": True,
                "deferred": bool(compile_result.get("deferred")),
                "reason": "single_slide_regenerate",
            },
        )
