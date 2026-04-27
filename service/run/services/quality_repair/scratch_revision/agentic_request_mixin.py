from __future__ import annotations

from pathlib import Path
from typing import Any

from .....design.skill_profile import DesignProfile


class AgenticScratchRevisionRequestMixin:
    orch: Any

    async def _repair_agentic_slide_js(
        self,
        *,
        run_id: str,
        run: Any,
        slide: Any,
        node: Any,
        design: DesignProfile,
        slides_dir: Path,
        effective_template_style: str,
        rule_issues: list[str],
    ) -> str | None:
        orch = self.orch
        slide_plan = await self._prepare_agentic_repair_slide_plan(
            run=run,
            slide=slide,
            node=node,
            design=design,
            slides_dir=slides_dir,
        )
        slide_brief = orch._build_slide_brief(
            run=run,
            node=node,
            slide_no=slide.slide_no,
            slide_plan=slide_plan,
        )
        try:
            fixed_js = await orch._call_llm_with_timeout_retry(
                run_id=run_id,
                phase=f"slide.{slide.slide_no}.polish.repair_js",
                action=lambda: orch.llm_client.critique_slide_js(
                    topic=run.input.topic,
                    template_style=effective_template_style,
                    slide_no=slide.slide_no,
                    target_slide_count=run.input.target_slide_count,
                    outline_node=node,
                    candidate_js=slide.js_code,
                    issues=rule_issues[:12],
                    failure_context=orch._build_slide_failure_context(
                        phase="polish.repair_js",
                        slide_js_path=Path(slide.js_path) if slide.js_path else None,
                        candidate_js=slide.js_code,
                        issues=rule_issues[:12],
                        diagnostics={"error_message": "qa polish requested"},
                    ),
                    visual_policy=run.input.visual_policy,
                    slide_plan=slide_plan,
                    repair_directives=rule_issues[:12],
                    preview_text="",
                    slide_brief=slide_brief,
                ),
            )
        except Exception as exc:
            await orch._append_quality_entry(
                run_id=run_id,
                entry={
                    "slide_no": slide.slide_no,
                    "passed_round": 1,
                    "issues_last_round": [
                        f"polish skipped: {orch._exception_reason(exc)}"
                    ],
                    "engine": orch.settings.generation_engine,
                    "repair_mode": "js_repair_skipped",
                },
            )
            return None
        return await self._finalize_agentic_repair_js(
            run_id=run_id,
            slide=slide,
            node=node,
            target_slide_count=run.input.target_slide_count,
            fixed_js=fixed_js,
        )
