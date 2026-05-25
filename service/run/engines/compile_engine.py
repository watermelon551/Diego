from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from .compile_local_runtime_mixin import CompileLocalRuntimeMixin
from .compile_pagevra_runtime_mixin import CompilePagevraRuntimeMixin
from .compile_pptd_runtime_mixin import CompilePptdRuntimeMixin
from .compile_script_bundle_mixin import CompileScriptBundleMixin
from ..results import ScratchCompileResult


class CompileEngine(
    CompileScriptBundleMixin,
    CompileLocalRuntimeMixin,
    CompilePagevraRuntimeMixin,
    CompilePptdRuntimeMixin,
):
    result_type = ScratchCompileResult

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.httpx = httpx

    async def compile_scratch_run(
        self,
        *,
        run_id: str,
        slides_dir: Path,
        slide_count: int,
        theme: dict[str, Any],
    ) -> ScratchCompileResult:
        requested_provider = str(
            getattr(self.runtime.settings, "compile_provider", "none") or "none"
        ).strip().lower()
        if requested_provider == "pptd":
            pptd_result = await self._compile_scratch_via_pptd(
                run_id=run_id,
                slides_dir=slides_dir,
                slide_count=slide_count,
                theme=theme,
            )
            return ScratchCompileResult(
                **{
                    **pptd_result.__dict__,
                    "requested_provider": pptd_result.requested_provider or "pptd",
                }
            )
        compile_js = self._ensure_compile_script(
            slides_dir=slides_dir,
            slide_count=slide_count,
            theme=theme,
        )
        if requested_provider == "none":
            return ScratchCompileResult(
                ok=True,
                compile_js_path=compile_js,
                pptx_path=None,
                return_code=None,
                reason="external_compile_deferred",
                provider="none",
                deferred=True,
                bundle_ready=True,
                requested_provider="none",
            )
        if requested_provider == "local":
            local_result = await self._compile_scratch_local(slides_dir=slides_dir)
            return ScratchCompileResult(
                **{**local_result.__dict__, "requested_provider": "local"}
            )
        if requested_provider == "pagevra":
            pagevra_result = await self._compile_scratch_via_pagevra(
                run_id=run_id,
                slides_dir=slides_dir,
                theme=theme,
            )
            return ScratchCompileResult(
                **{
                    **pagevra_result.__dict__,
                    "requested_provider": pagevra_result.requested_provider or "pagevra",
                }
            )
        raise ValueError(f"unsupported compile provider: {requested_provider}")

    async def build_compile_bundle(self, run_id: str) -> dict[str, Any]:
        run = await self.runtime.store.get_run(run_id)
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        generation_mode = getattr(getattr(run, "input", None), "generation_mode", None)
        if str(getattr(generation_mode, "value", generation_mode)) != "scratch":
            raise ValueError(f"compile bundle is only available for scratch runs: {run_id}")
        slides_dir = Path(run.artifact_dir) / "slides"
        slide_count = len(getattr(run, "slides", []) or [])
        theme: dict[str, Any] = {}
        resolver = getattr(self.runtime, "_resolve_run_design", None)
        if callable(resolver):
            theme = dict(getattr(resolver(run), "theme", {}) or {})
        self._restore_scratch_slides_from_run(run=run, slides_dir=slides_dir)
        self._ensure_compile_script(
            slides_dir=slides_dir,
            slide_count=slide_count,
            theme=theme,
        )
        return await self._build_scratch_compile_bundle(
            run=run,
            slides_dir=slides_dir,
            theme=theme,
        )
