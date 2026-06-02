from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from ...models import EventType, OutlineNode, RunRecord
from ..types import SlideGenerationError, VisualPolicyUnsatisfiedError


class ScratchSlideBatchMixin:
    async def _generate_slide_batch(
        self,
        *,
        run_id: str,
        run: RunRecord,
        design: Any,
    ) -> list[dict[str, Any]]:
        orch = self.orch
        artifact_dir = Path(run.artifact_dir)
        slides_dir = artifact_dir / "slides"
        output_dir = slides_dir / "output"
        imgs_dir = slides_dir / "imgs"
        slides_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        imgs_dir.mkdir(parents=True, exist_ok=True)

        slide_start = time.perf_counter()
        sem = asyncio.Semaphore(
            min(5, orch.slide_concurrency, orch.llm_request_concurrency)
        )

        async def generate_one(slide_no: int, node: OutlineNode) -> None:
            async with sem:
                await orch._publish(
                    run_id,
                    EventType.SLIDE_STARTED,
                    {"slide_no": slide_no, "page_type": node.page_type.value},
                )
                try:
                    artifact = await orch.scratch_engine.generate_slide(
                        run_id=run_id,
                        slide_no=slide_no,
                        node=node,
                        design=design,
                    )
                except (VisualPolicyUnsatisfiedError, SlideGenerationError):
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
                preview = await orch.render_slide_preview_or_fallback(
                    run_id=run_id,
                    slide_no=slide_no,
                    slide_js_path=Path(str(artifact.js_path or "")),
                    theme=design.theme,
                )
                await orch._publish(
                    run_id,
                    EventType.SLIDE_GENERATED,
                    {
                        "slide_no": slide_no,
                        "status": artifact.status,
                        "preview": preview.get("preview"),
                        "preview_format": "svg",
                        "svg_data_url": preview.get("svg_data_url"),
                        "preview_width": preview.get("width", 1280),
                        "preview_height": preview.get("height", 720),
                        "is_final": True,
                    },
                )

        tasks = [
            generate_one(i, node)
            for i, node in enumerate(run.outline.nodes, start=1)
        ]
        timeout_sec = float(getattr(orch.settings, "slide_generation_timeout_sec", 9000.0) or 9000.0)
        timed_out = False
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(0.001, timeout_sec),
            )
        except asyncio.TimeoutError:
            timed_out = True
            results = []
        await orch.store.update_run(
            run_id,
            lambda r: setattr(
                r.stage_timings,
                "slide_ms",
                int((time.perf_counter() - slide_start) * 1000),
            ),
        )
        failures: list[dict[str, Any]] = []
        if timed_out:
            latest_run = await orch.store.get_run(run_id)
            completed_slides = len(latest_run.slides) if latest_run is not None else 0
            failures.append(
                {
                    "slide_no": 0,
                    "phase": "slides.batch",
                    "reason": f"slide generation exceeded {timeout_sec:.0f}s",
                    "details": {
                        "error_type": "SlideGenerationTimeout",
                        "timeout_sec": timeout_sec,
                        "completed_slides": completed_slides,
                        "target_slide_count": len(run.outline.nodes),
                    },
                }
            )
            return failures
        if any(isinstance(item, VisualPolicyUnsatisfiedError) for item in results):
            failures.append(
                {
                    "slide_no": 0,
                    "phase": "slides.batch",
                    "reason": "visual policy unsatisfied",
                    "details": {"error_type": "VisualPolicyUnsatisfiedError"},
                }
            )
            return failures
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
        return failures
