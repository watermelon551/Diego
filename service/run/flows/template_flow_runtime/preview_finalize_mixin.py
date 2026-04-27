from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ....models import EventType, GenerationMode


class TemplateFlowPreviewFinalizeMixin:
    orch: Any

    async def _publish_template_previews(
        self,
        *,
        run_id: str,
        artifacts: list[Any],
        theme: dict[str, Any],
    ) -> bool:
        orch = self.orch
        try:
            previews = await asyncio.gather(
                *(
                    orch.render_slide_preview_or_fallback(
                        run_id=run_id,
                        slide_no=item.slide_no,
                        slide_js_path=Path(str(item.js_path or "")),
                        theme=theme,
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
            return False
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
        return True

    async def _finalize_template_run(
        self,
        *,
        run_id: str,
        edited: Path,
        template_compile_js: Path,
        design: Any,
    ) -> None:
        orch = self.orch
        await orch._publish(
            run_id,
            EventType.COMPILE_COMPLETED,
            {
                "file": str(edited),
                "mode": "template",
                "compile_js": str(template_compile_js),
                "provider": None,
                "requested_provider": "none",
            },
        )
        await orch.finalize_quality_stage.execute(
            run_id=run_id,
            mode=GenerationMode.TEMPLATE,
            design=design,
            from_stage="COMPILING",
            success_reason="template compile+qa completed",
        )
