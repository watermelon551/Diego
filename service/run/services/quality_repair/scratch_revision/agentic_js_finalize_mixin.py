from __future__ import annotations

from typing import Any

from .....models import EventType


class AgenticScratchRevisionJsFinalizeMixin:
    orch: Any

    async def _finalize_agentic_repair_js(
        self,
        *,
        run_id: str,
        slide: Any,
        node: Any,
        target_slide_count: int,
        fixed_js: str,
    ) -> str:
        orch = self.orch
        fixed_js, normalize_fixes = orch._normalize_generated_slide_js(
            fixed_js,
            slide_no=slide.slide_no,
            node=node,
            target_slide_count=target_slide_count,
        )
        auto_fixes: list[str] = []
        if orch.slide_auto_canonicalize:
            fixed_js, auto_fixes = orch._auto_canonicalize_slide_js(
                fixed_js,
                slide_no=slide.slide_no,
                node=node,
                target_slide_count=target_slide_count,
            )
        if normalize_fixes or auto_fixes:
            await orch._publish(
                run_id,
                EventType.SLIDE_AUTO_FIX_APPLIED,
                {
                    "slide_no": slide.slide_no,
                    "round": 0,
                    "candidate": 1,
                    "fixes": orch._dedupe_preserve_order(
                        normalize_fixes + auto_fixes
                    )[:24],
                },
            )
        return orch._apply_local_js_guardrails(
            js_code=fixed_js,
            slide_no=slide.slide_no,
            page_type=node.page_type,
        )
