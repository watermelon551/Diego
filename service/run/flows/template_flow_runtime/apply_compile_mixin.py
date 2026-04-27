from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class TemplateFlowApplyCompileMixin:
    orch: Any

    async def _apply_template_generation(
        self,
        *,
        run_id: str,
        unpacked: Path,
        design: Any,
    ) -> tuple[list[Any], float] | None:
        orch = self.orch
        compile_start = time.perf_counter()
        try:
            artifacts = await orch.template_engine.apply_template_nodes_once(
                run_id=run_id,
                unpacked=unpacked,
                design=design,
                use_review=False,
                forced_issues=None,
            )
        except Exception as exc:
            if await self._fail_template_apply_exception(run_id, exc):
                return None
            raise
        if not artifacts:
            await orch._fail_run(
                run_id, "SLIDES_GENERATING", "TEMPLATE_APPLY_FAILED", retryable=True
            )
            return None
        return artifacts, compile_start

    async def _compile_template_outputs(
        self,
        *,
        run_id: str,
        artifacts: list[Any],
        compile_start: float,
        unpacked: Path,
        edited: Path,
        template_slides_dir: Path,
        template_compile_js: Path,
    ) -> bool:
        orch = self.orch
        orch.template_engine.pack_template_unpacked(unpacked=unpacked, edited=edited)

        compiled = await orch.template_engine.compile_template_js(
            template_slides_dir=template_slides_dir
        )
        if not compiled:
            await orch._fail_run(
                run_id, "COMPILING", "TEMPLATE_JS_COMPILE_FAILED", retryable=True
            )
            return False

        def apply_compile(r) -> None:
            r.compile_js_path = str(template_compile_js)
            r.pptx_path = str(edited)
            r.compile_requested_provider = None
            r.compile_provider = None
            r.compile_status = "not_requested"
            r.compile_bundle_ready = False
            r.compile_error_code = None
            r.compile_error_details = {}
            r.stage_timings.compile_ms = int(
                (time.perf_counter() - compile_start) * 1000
            )
            r.slides = artifacts
            r.citation_map = {item.slide_no: list(item.citations) for item in artifacts}
            r.render_version += 1

        await orch.store.update_run(run_id, apply_compile)
        return True
