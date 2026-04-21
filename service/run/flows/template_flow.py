from __future__ import annotations

import asyncio
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from ...models import EventType, GenerationMode, RunStatus
from ..types import (
    TemplateAssetError,
    TemplateLayoutConflictError,
    TemplateSlotMappingError,
)


class TemplateFlowService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def execute(self, run_id: str) -> None:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        assert run is not None and run.outline is not None
        orch._init_run_llm_budget(
            run_id=run_id, target_slide_count=run.input.target_slide_count
        )
        effective_template_style = orch._resolved_template_style(run)
        design = orch._resolve_design_profile(
            topic=run.input.topic,
            template_style=effective_template_style,
            requirements_report=(
                run.research_report if isinstance(run.research_report, dict) else {}
            ),
        )
        if not run.input.template_id:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_ID_MISSING", retryable=False
            )
            return

        template_record = await orch.store.get_template(run.input.template_id)
        if template_record is None:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_NOT_FOUND", retryable=False
            )
            return

        await orch.store.update_run(
            run_id, lambda r: setattr(r, "status", RunStatus.COMPILING)
        )
        await orch._publish(run_id, EventType.COMPILE_STARTED, {"mode": "template"})

        (
            template_dir,
            work_template,
            template_md,
            unpacked,
            edited,
            template_slides_dir,
            template_compile_js,
            _,
        ) = orch.template_engine.template_work_paths(Path(run.artifact_dir))
        template_dir.mkdir(parents=True, exist_ok=True)
        unpacked.mkdir(parents=True, exist_ok=True)
        src_template = Path(template_record.path)
        shutil.copy2(src_template, work_template)
        markitdown_template = await asyncio.to_thread(
            orch.subprocess.run,
            [sys.executable, "-m", "markitdown", str(work_template)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if markitdown_template.returncode == 0 and markitdown_template.stdout:
            template_md.write_text(markitdown_template.stdout, encoding="utf-8")
        elif markitdown_template.returncode != 0:
            markitdown_stderr = (markitdown_template.stderr or "").lower()
            markitdown_stdout = (markitdown_template.stdout or "").lower()
            if (
                "template parse error" in markitdown_stderr
                or "template parse error" in markitdown_stdout
            ):
                await orch._fail_run(
                    run_id,
                    "SLIDES_GENERATING",
                    "TEMPLATE_MARKITDOWN_FAILED",
                    retryable=False,
                )
                return
            await orch._append_quality_entry(
                run_id=run_id,
                entry={
                    "stage": "template.markitdown.preflight",
                    "status": "degraded_skip",
                    "reason": orch._summarize_process_failure(
                        stderr=markitdown_template.stderr or "",
                        stdout=markitdown_template.stdout or "",
                    )[0],
                },
            )

        if unpacked.exists():
            shutil.rmtree(unpacked)
        unpacked.mkdir(parents=True, exist_ok=True)
        with ZipFile(work_template, "r") as zin:
            zin.extractall(unpacked)

        compile_start = time.perf_counter()
        try:
            artifacts = await orch.template_engine.apply_template_nodes_once(
                run_id=run_id,
                unpacked=unpacked,
                design=design,
                use_review=False,
                forced_issues=None,
            )
        except TemplateAssetError:
            await orch._fail_run(
                run_id,
                "SLIDES_GENERATING",
                "TEMPLATE_ASSET_FETCH_FAILED",
                retryable=False,
            )
            return
        except TemplateSlotMappingError:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False
            )
            return
        except TemplateLayoutConflictError:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False
            )
            return
        if not artifacts:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_APPLY_FAILED", retryable=True
            )
            return
        orch.template_engine.pack_template_unpacked(unpacked=unpacked, edited=edited)

        compiled = await orch.template_engine.compile_template_js(
            template_slides_dir=template_slides_dir
        )
        if not compiled:
            await orch._fail_run(
                run_id, "COMPILING", "TEMPLATE_JS_COMPILE_FAILED", retryable=True
            )
            return

        def apply_compile(r: RunRecord) -> None:
            r.compile_js_path = str(template_compile_js)
            r.pptx_path = str(edited)
            r.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            r.slides = artifacts
            r.citation_map = {item.slide_no: list(item.citations) for item in artifacts}
            r.render_version += 1

        await orch.store.update_run(run_id, apply_compile)
        try:
            previews = await asyncio.gather(
                *(
                    orch.render_slide_preview_or_fallback(
                        run_id=run_id,
                        slide_no=item.slide_no,
                        slide_js_path=Path(str(item.js_path or "")),
                        theme=design.theme,
                    )
                    for item in artifacts
                )
            )
        except Exception as exc:
            await orch._fail_run(
                run_id,
                "COMPILING",
                "SLIDE_PREVIEW_RENDER_FAILED",
                retryable=True,
                error_details={
                    "reason": orch._exception_reason(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return
        for artifact, preview in zip(artifacts, previews, strict=False):
            await orch._publish(
                run_id,
                EventType.SLIDE_GENERATED,
                {
                    "slide_no": artifact.slide_no,
                    "status": artifact.status,
                    "preview": preview.get("preview"),
                    "preview_format": "svg",
                    "svg_data_url": preview.get("svg_data_url"),
                    "preview_width": preview.get("width", 1280),
                    "preview_height": preview.get("height", 720),
                    "is_final": True,
                },
            )
        await orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(edited),
                "mode": "template",
                "compile_js": str(template_compile_js),
            },
        )
        await orch.finalize_quality_stage.execute(
            run_id=run_id,
            mode=GenerationMode.TEMPLATE,
            design=design,
            from_stage="COMPILING",
            success_reason="template compile+qa completed",
        )
