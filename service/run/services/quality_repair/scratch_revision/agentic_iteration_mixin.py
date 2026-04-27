from __future__ import annotations

from pathlib import Path
from typing import Any

from .....design.skill_profile import DesignProfile


class AgenticScratchRevisionIterationMixin:
    orch: Any

    async def _revise_agentic_scratch_slides(
        self,
        *,
        run_id: str,
        run: Any,
        design: DesignProfile,
        effective_template_style: str,
        forced_issues: list[str] | None,
    ) -> bool:
        slides_dir = Path(run.artifact_dir) / "slides"
        for slide in sorted(run.slides, key=lambda x: x.slide_no):
            node = run.outline.nodes[slide.slide_no - 1]
            rule_issues = self._resolved_rule_issues(
                forced_issues=forced_issues,
                qa_report=run.qa_report,
            )
            fixed_js = await self._repair_agentic_slide_js(
                run_id=run_id,
                run=run,
                slide=slide,
                node=node,
                design=design,
                slides_dir=slides_dir,
                effective_template_style=effective_template_style,
                rule_issues=rule_issues,
            )
            if fixed_js is None:
                continue

            citations = self.orch._normalize_citations(
                slide.citations or run.input.rag_source_ids,
                run.input.rag_source_ids,
                slide.slide_no,
            )
            reviewed = self.extract_candidate_from_js(
                js_code=fixed_js,
                fallback_node=node,
                citations=citations,
            )
            chart_plan = self._chart_plan_for_reviewed(
                node=node,
                reviewed=reviewed,
                source_refs=citations,
            )
            slide_path = slides_dir / f"slide-{slide.slide_no:02d}.js"
            slide_path.write_text(fixed_js, encoding="utf-8")
            slide.js_code = fixed_js
            slide.citations = citations
            await self._append_chart_truth_entry(
                run_id=run_id,
                slide_no=slide.slide_no,
                chart_plan=chart_plan,
            )
            await self.orch._append_quality_entry(
                run_id=run_id,
                entry={
                    "slide_no": slide.slide_no,
                    "passed_round": 1,
                    "issues_last_round": [str(item) for item in rule_issues],
                    "engine": self.orch.settings.generation_engine,
                    "repair_mode": "js_repair",
                },
            )
        return True

    def _resolved_rule_issues(
        self,
        *,
        forced_issues: list[str] | None,
        qa_report: Any,
    ) -> list[str]:
        if forced_issues:
            return [str(item) for item in forced_issues]
        if isinstance(qa_report, dict) and isinstance(qa_report.get("issues", []), list):
            return [str(item) for item in qa_report.get("issues", [])]
        return []
