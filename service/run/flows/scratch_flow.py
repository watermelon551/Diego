from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from ...models import EventType, GenerationMode, OutlineNode, RunRecord, RunStatus, VisualPolicy
from ..types import SlideGenerationError, VisualPolicyUnsatisfiedError


class ScratchFlowService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def execute(self, run_id: str) -> None:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        assert run is not None and run.outline is not None
        orch._init_run_llm_budget(run_id=run_id, target_slide_count=run.input.target_slide_count)
        if run.input.visual_policy == VisualPolicy.MEDIA_REQUIRED and orch.settings.asset_provider == "none":
            await orch._fail_run(run_id, "SLIDES_GENERATING", "VISUAL_POLICY_UNSATISFIED", retryable=False)
            return
        effective_template_style = orch._resolved_template_style(run)
        design = orch._resolve_design_profile(topic=run.input.topic, template_style=effective_template_style, requirements_report=run.research_report if isinstance(run.research_report, dict) else {})

        artifact_dir = Path(run.artifact_dir)
        slides_dir = artifact_dir / "slides"
        output_dir = slides_dir / "output"
        imgs_dir = slides_dir / "imgs"
        slides_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        imgs_dir.mkdir(parents=True, exist_ok=True)

        slide_start = time.perf_counter()
        sem = asyncio.Semaphore(min(5, orch.slide_concurrency, orch.llm_request_concurrency))

        async def generate_one(slide_no: int, node: OutlineNode) -> None:
            async with sem:
                await orch._publish(run_id, EventType.SLIDE_STARTED, {"slide_no": slide_no, "page_type": node.page_type.value})
                try:
                    artifact = await orch._generate_skill_slide(run_id=run_id, slide_no=slide_no, node=node, design=design)
                except VisualPolicyUnsatisfiedError:
                    raise
                except SlideGenerationError:
                    raise
                except Exception as exc:
                    raise SlideGenerationError(
                        slide_no=slide_no,
                        phase="slide.pipeline",
                        reason=orch._exception_reason(exc),
                        details={"error_type": type(exc).__name__},
                    ) from exc

                def apply_slide(r: RunRecord) -> None:
                    r.slides.append(artifact)
                    r.citation_map[slide_no] = artifact.citations

                await orch.store.update_run(run_id, apply_slide)
                await orch._publish(run_id, EventType.SLIDE_GENERATED, {"slide_no": slide_no, "status": artifact.status})

        results = await asyncio.gather(
            *(generate_one(i, node) for i, node in enumerate(run.outline.nodes, start=1)),
            return_exceptions=True,
        )
        if any(isinstance(item, VisualPolicyUnsatisfiedError) for item in results):
            await orch._fail_run(run_id, "SLIDES_GENERATING", "VISUAL_POLICY_UNSATISFIED", retryable=False)
            return
        failures: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, Exception):
                continue
            if isinstance(item, SlideGenerationError):
                payload = item.to_payload()
            else:
                payload = {
                    "slide_no": 0,
                    "phase": "slides.batch",
                    "reason": orch._exception_reason(item),
                    "details": {"error_type": type(item).__name__},
                }
            failures.append(payload)
            await orch._publish(run_id, EventType.SLIDE_FAILED, payload)
        if failures:
            await orch._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "SLIDE_LLM_ERROR",
                retryable=True,
                error_details={
                    "failure_count": len(failures),
                    "first_failure": failures[0],
                    "failures": failures[:8],
                },
            )
            return

        await orch.store.update_run(
            run_id,
            lambda r: setattr(r.stage_timings, "slide_ms", int((time.perf_counter() - slide_start) * 1000)),
        )
        await orch.store.update_run(run_id, lambda r: setattr(r, "status", RunStatus.COMPILING))
        await orch._publish(run_id, EventType.COMPILE_STARTED, {})

        compile_start = time.perf_counter()
        run = await orch.store.get_run(run_id)
        assert run is not None
        sorted_slides = sorted(run.slides, key=lambda x: x.slide_no)
        compile_js = slides_dir / "compile.js"
        compile_js.write_text(orch._build_compile_script(total=len(sorted_slides), theme=design.theme), encoding="utf-8")

        compile_cmd = ["node", "compile.js"]
        result = await asyncio.to_thread(
            orch.subprocess.run,
            compile_cmd,
            cwd=slides_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        compile_reason = orch._known_compile_stderr_reason(stderr=result.stderr or "", stdout=result.stdout or "")
        if result.returncode != 0 or compile_reason:
            await orch._fail_run(
                run_id,
                "COMPILING",
                "COMPILE_SCRIPT_FAILED",
                retryable=True,
                error_details={
                    "return_code": result.returncode,
                    "reason": compile_reason or "compile.js returned non-zero",
                },
            )
            return

        pptx_path = output_dir / "presentation.pptx"

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = str(compile_js)
            r.pptx_path = str(pptx_path)
            r.stage_timings.compile_ms = int((time.perf_counter() - compile_start) * 1000)

        await orch.store.update_run(run_id, apply_compile)
        await orch._publish(run_id, EventType.COMPILE_COMPLETED, {"file": str(pptx_path)})
        qa_timeout_sec = max(1.0, float(orch.settings.qa_finalize_timeout_sec))
        try:
            post_compile_ok = await asyncio.wait_for(
                orch._complete_post_compile_quality(run_id=run_id, mode=GenerationMode.SCRATCH, design=design),
                timeout=qa_timeout_sec,
            )
        except asyncio.TimeoutError:
            await orch._fail_run(
                run_id,
                "COMPILING",
                "FINALIZE_TIMEOUT",
                retryable=True,
                error_details={"reason": f"post-compile QA exceeded {qa_timeout_sec:.0f}s", "mode": "scratch"},
            )
            return
        if not post_compile_ok:
            return
        await orch._finalize_run_success(run_id, from_stage="COMPILING", reason="scratch compile+qa completed")

