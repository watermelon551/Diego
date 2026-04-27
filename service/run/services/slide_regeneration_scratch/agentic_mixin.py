from __future__ import annotations

from ....models import EventType, OutlineNode


class SlideRegenerationAgenticScratchMixin:
    async def _regenerate_agentic_scratch_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        run,
        node: OutlineNode,
        slide,
        effective_template_style: str,
        rule_violations: list[str],
    ):
        orch = self.orch
        js_code = await orch._call_llm_with_timeout_retry(
            run_id=run_id,
            phase=f"slide.{slide_no}.regenerate.repair",
            action=lambda: orch.llm_client.critique_slide_js(
                topic=run.input.topic,
                template_style=effective_template_style,
                slide_no=slide_no,
                target_slide_count=run.input.target_slide_count,
                outline_node=node,
                candidate_js=slide.js_code,
                issues=rule_violations,
                failure_context={"trigger": "single_slide_regenerate"},
                visual_policy=run.input.visual_policy,
            ),
        )
        js_code, normalize_fixes = orch._normalize_generated_slide_js(
            js_code,
            slide_no=slide_no,
            node=node,
            target_slide_count=run.input.target_slide_count,
        )
        auto_fixes: list[str] = []
        if orch.slide_auto_canonicalize:
            js_code, auto_fixes = orch._auto_canonicalize_slide_js(
                js_code,
                slide_no=slide_no,
                node=node,
                target_slide_count=run.input.target_slide_count,
            )
        if normalize_fixes or auto_fixes:
            await orch._publish(
                run_id,
                EventType.SLIDE_AUTO_FIX_APPLIED,
                {
                    "slide_no": slide_no,
                    "round": 1,
                    "candidate": 1,
                    "fixes": orch._dedupe_preserve_order(
                        normalize_fixes + auto_fixes
                    )[:24],
                },
            )
        js_code = orch._apply_local_js_guardrails(
            js_code=js_code,
            slide_no=slide_no,
            page_type=node.page_type,
        )
        reviewed = orch.quality_engine.extract_candidate_from_js(
            js_code=js_code,
            fallback_node=node,
            citations=slide.citations,
        )
        return reviewed, js_code
