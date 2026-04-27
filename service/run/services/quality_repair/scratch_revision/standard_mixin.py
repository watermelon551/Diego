from __future__ import annotations

from pathlib import Path
from typing import Any

from .....design.skill_profile import DesignProfile


class StandardScratchRevisionMixin:
    orch: Any

    async def _revise_standard_scratch_slides(
        self,
        *,
        run_id: str,
        run: Any,
        design: DesignProfile,
        effective_template_style: str,
        forced_issues: list[str] | None,
    ) -> bool:
        orch = self.orch
        for slide in sorted(run.slides, key=lambda x: x.slide_no):
            node = run.outline.nodes[slide.slide_no - 1]
            candidate = self.extract_candidate_from_js(
                js_code=slide.js_code,
                fallback_node=node,
                citations=slide.citations,
            )
            try:
                reviewed = await orch._call_llm_with_timeout_retry(
                    run_id=run_id,
                    phase=f"slide.{slide.slide_no}.polish.review",
                    action=lambda: orch.llm_client.review_slide(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        slide_no=slide.slide_no,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=node,
                        candidate=candidate,
                        rule_violations=forced_issues or run.qa_report.get("issues", []),
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
                        "repair_mode": "review_skipped",
                    },
                )
                continue
            chart_plan = self._chart_plan_for_reviewed(
                node=node,
                reviewed=reviewed,
                source_refs=slide.citations,
            )
            fixed_js = orch._render_skill_slide_js(
                slide_no=slide.slide_no,
                total=run.input.target_slide_count,
                node=node,
                generated=reviewed,
                design=design,
                chart_plan=chart_plan,
            )
            slide_path = Path(run.artifact_dir) / "slides" / f"slide-{slide.slide_no:02d}.js"
            slide_path.write_text(fixed_js, encoding="utf-8")
            slide.js_code = fixed_js
            await self._append_chart_truth_entry(
                run_id=run_id,
                slide_no=slide.slide_no,
                chart_plan=chart_plan,
            )
        return True
