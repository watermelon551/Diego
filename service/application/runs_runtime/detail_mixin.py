from __future__ import annotations

from pathlib import Path
from typing import Any

from ...models import (
    CompileBundleResult,
    CompileResult,
    GenerationResult,
    RunDetailResponse,
)


class RunApplicationDetailMixin:
    def _compile_bundle_entrypoint(self, run: Any) -> str:
        provider = str(getattr(run, "compile_provider", "") or "").strip().lower()
        requested_provider = str(
            getattr(run, "compile_requested_provider", "") or ""
        ).strip().lower()
        compile_path = Path(str(getattr(run, "compile_js_path", "") or ""))
        if (
            provider == "pptd"
            or requested_provider == "pptd"
            or compile_path.suffix == ".pptd"
        ):
            return "slides/compile_pptd_bundle.js"
        return "slides/compile.js"

    async def get_run_detail(self, run_id: str) -> RunDetailResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "ppt") != "ppt":
            return None
        generation_mode_raw = getattr(getattr(run, "input", None), "generation_mode", None)
        generation_mode = str(
            getattr(generation_mode_raw, "value", generation_mode_raw) or ""
        )
        pptx_path = str(run.pptx_path or "").strip()
        pptx_ready = bool(pptx_path and Path(pptx_path).exists() and Path(pptx_path).is_file())
        artifacts: dict[str, Any] = {}
        if pptx_path:
            artifacts["pptx"] = {"path": pptx_path, "downloadable": pptx_ready}
        compile_bundle_ready = bool(
            generation_mode == "scratch"
            and (
                getattr(run, "compile_bundle_ready", False)
                or str(run.compile_js_path or "").strip()
            )
        )
        compile_bundle_entrypoint = (
            self._compile_bundle_entrypoint(run) if compile_bundle_ready else None
        )
        if compile_bundle_ready:
            artifacts["compile_bundle"] = {
                "available": True,
                "entrypoint": compile_bundle_entrypoint,
                "provider": "diego",
                "mode": generation_mode,
                "build_endpoint": f"/v1/ppt/runs/{run.run_id}/artifacts/compile-bundle",
            }
        generation_result = GenerationResult(
            mode=run.input.generation_mode,
            artifact_dir=str(run.artifact_dir or ""),
            outline_ready=run.outline is not None,
            slide_count=len(run.slides),
            slide_artifacts_ready=bool(run.slides),
            citation_map_ready=bool(run.citation_map),
            compile_bundle_ready=compile_bundle_ready,
            compile_bundle_entrypoint=compile_bundle_entrypoint,
        )
        compile_bundle = CompileBundleResult(
            status="ready" if compile_bundle_ready else "not_available",
            provider="diego",
            available=compile_bundle_ready,
            entrypoint=compile_bundle_entrypoint,
            build_endpoint=(
                f"/v1/ppt/runs/{run.run_id}/artifacts/compile-bundle"
                if compile_bundle_ready
                else None
            ),
            mode=generation_mode if compile_bundle_ready else None,
        )
        compile_result_status = str(
            getattr(run, "compile_status", "not_requested") or "not_requested"
        )
        compile_requested_provider = getattr(run, "compile_requested_provider", None)
        compile_provider = run.compile_provider
        compile_artifact_path = run.pptx_path
        compile_artifact_ready = pptx_ready
        if generation_mode == "template":
            compile_result_status = "not_requested"
            compile_requested_provider = None
            compile_provider = None
            compile_artifact_path = None
            compile_artifact_ready = False
        compile_result = CompileResult(
            status=compile_result_status,
            requested_provider=compile_requested_provider,
            provider=compile_provider,
            bundle_ready=compile_bundle_ready,
            artifact_path=compile_artifact_path,
            artifact_ready=compile_artifact_ready,
            fallback_used=bool(run.compile_fallback_used),
            fallback_from=(
                run.compile_error_details.get("fallback_from")
                if isinstance(getattr(run, "compile_error_details", {}), dict)
                else None
            ),
            error_code=getattr(run, "compile_error_code", None),
            error_details=(
                dict(getattr(run, "compile_error_details", {}) or {})
                if isinstance(getattr(run, "compile_error_details", {}), dict)
                else {}
            ),
        )
        return RunDetailResponse(
            run_id=run.run_id,
            trace_id=run.trace_id,
            status=run.status,
            pptx_ready=pptx_ready,
            artifacts=artifacts,
            outline=run.outline,
            outline_history=run.outline_history,
            slides=run.slides,
            citation_map=run.citation_map,
            stage_timings=run.stage_timings,
            render_version=run.render_version,
            error_code=run.error_code,
            failed_stage=run.failed_stage,
            retryable=run.retryable,
            error_details=run.error_details,
            generation_result=generation_result,
            compile_bundle=compile_bundle,
            compile_result=compile_result,
            compile_js_path=run.compile_js_path,
            pptx_path=run.pptx_path,
            compile_requested_provider=getattr(run, "compile_requested_provider", None),
            compile_provider=run.compile_provider,
            compile_fallback_used=run.compile_fallback_used,
            qa_report=run.qa_report,
            template_mapping_report=run.template_mapping_report,
            chart_truth_report=run.chart_truth_report,
            repair_history=run.repair_history,
            quality_report=run.quality_report,
            quality_gate_report=run.quality_gate_report,
            research_report=run.research_report,
            candidate_selection_report=run.candidate_selection_report,
            template_layout_report=run.template_layout_report,
            artifact_cleanup_report=run.artifact_cleanup_report,
            events=run.events,
        )
