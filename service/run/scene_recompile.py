from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import GenerationMode, RunRecord


async def recompile_run_after_scene_save(*, orchestrator: Any, run: RunRecord) -> Any:
    if run.input.generation_mode == GenerationMode.TEMPLATE:
        (
            _,
            _,
            _,
            _,
            _,
            template_slides_dir,
            template_compile_js,
            template_compiled_pptx,
        ) = orchestrator.template_engine.template_work_paths(Path(run.artifact_dir))
        compiled = await orchestrator.template_engine.compile_template_js(
            template_slides_dir=template_slides_dir
        )
        if not compiled:
            raise RuntimeError("template scene save compile failed")
        return orchestrator.compile_engine.result_type(
            ok=True,
            compile_js_path=template_compile_js,
            pptx_path=template_compiled_pptx,
            return_code=0,
            reason="",
            provider="none",
            fallback_used=False,
            requested_provider="none",
        )
    compile_result = await orchestrator.compile_engine.compile_scratch_run(
        run_id=run.run_id,
        slides_dir=Path(run.artifact_dir) / "slides",
        slide_count=len(run.slides),
        theme=orchestrator._resolve_run_design(run).theme,
    )
    if not compile_result.ok:
        raise RuntimeError(str(compile_result.reason or "scene save recompile failed"))
    return compile_result
