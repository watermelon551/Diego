from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ...design.skill_profile import DesignProfile, allowed_layouts_for
from ...llm import GeneratedSlide
from ...models import EventType, GenerationMode, OutlineNode, RunRecord, RunStatus, SlidePageType
from ..types import TemplateLayoutConflictError, TemplateSlotMappingError


class QualityRepairService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def complete_post_compile_quality(
        self,
        *,
        run_id: str,
        mode: GenerationMode,
        design: DesignProfile,
    ) -> bool:
        orch = self.orch
        if not orch.settings.qa_enabled:
            return True
        if mode == GenerationMode.TEMPLATE:
            qa_ok = await orch._run_skill_qa(run_id, mode=mode)
            if qa_ok:
                return True
            latest = await orch.store.get_run(run_id)
            if latest is not None and latest.status == RunStatus.FAILED:
                return False
            qa_details = await orch._persist_qa_failure_artifacts(run_id=run_id, mode=mode)
            await orch._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False, error_details=qa_details)
            return False

        polish_ok = await self.mandatory_polish_cycle(run_id, mode=mode, design=design)
        if not polish_ok:
            latest = await orch.store.get_run(run_id)
            if latest is not None and latest.status == RunStatus.FAILED:
                return False
            qa_details = await orch._persist_qa_failure_artifacts(run_id=run_id, mode=mode)
            await orch._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False, error_details=qa_details)
            return False
        latest_after_polish = await orch.store.get_run(run_id)
        qa_ok = bool(
            latest_after_polish
            and isinstance(latest_after_polish.qa_report, dict)
            and latest_after_polish.qa_report.get("passed", False)
        )
        if not qa_ok:
            qa_ok = await self.repair_loop(run_id, mode=mode, design=design)
        if qa_ok:
            return True
        latest = await orch.store.get_run(run_id)
        if latest is not None and latest.status == RunStatus.FAILED:
            return False
        qa_details = await orch._persist_qa_failure_artifacts(run_id=run_id, mode=mode)
        await orch._fail_run(run_id, "COMPILING", "QA_FAILED", retryable=False, error_details=qa_details)
        return False

    async def mandatory_polish_cycle(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        orch = self.orch
        await orch._publish(run_id, EventType.REPAIR_STARTED, {"round": 0, "mode": mode.value, "reason": "mandatory_verify_cycle"})
        run = await orch.store.get_run(run_id)
        if run is None:
            return False
        if mode == GenerationMode.SCRATCH:
            revised = await self.revise_scratch_slides(
                run_id=run_id,
                design=design,
                forced_issues=["mandatory polish cycle"],
            )
            if not revised:
                return False
            compiled = await orch._compile_scratch_slides(run_id)
            if not compiled:
                return False
        else:
            try:
                revised_template = await orch._revise_template_slides(
                    run_id=run_id,
                    design=design,
                    forced_issues=["mandatory polish cycle"],
                )
            except TemplateSlotMappingError:
                await orch._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False)
                return False
            except TemplateLayoutConflictError:
                await orch._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False)
                return False
            if not revised_template:
                return False
        qa_ok = await orch._run_skill_qa(run_id, mode=mode)

        def apply_cycle(r: RunRecord) -> None:
            cycles = int(r.qa_report.get("verification_cycles", 0))
            r.qa_report["verification_cycles"] = cycles + 1

        await orch.store.update_run(run_id, apply_cycle)
        await orch._append_repair_history(
            run_id=run_id,
            entry={
                "round": 0,
                "mode": mode.value,
                "source": "latest_artifacts",
                "qa_passed": qa_ok,
            },
        )
        await orch._publish(
            run_id,
            EventType.REPAIR_ROUND_COMPLETED,
            {
                "round": 0,
                "mode": mode.value,
                "qa_passed": qa_ok,
                "source": "latest_artifacts",
            },
        )
        # Mandatory polish is an execution step, not a hard quality gate.
        # Even if qa_ok is False here, caller should continue into normal QA/repair flow.
        return True

    async def repair_loop(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        orch = self.orch
        for repair_round in range(1, orch.repair_rounds + 1):
            await orch._publish(run_id, EventType.REPAIR_STARTED, {"round": repair_round, "mode": mode.value})
            if mode == GenerationMode.SCRATCH:
                revised = await self.revise_scratch_slides(
                    run_id=run_id,
                    design=design,
                    forced_issues=None,
                )
                if not revised:
                    continue
                compiled = await orch._compile_scratch_slides(run_id)
                if not compiled:
                    continue
            else:
                try:
                    revised_template = await orch._revise_template_slides(
                        run_id=run_id,
                        design=design,
                        forced_issues=None,
                    )
                except TemplateSlotMappingError:
                    await orch._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False)
                    return False
                except TemplateLayoutConflictError:
                    await orch._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False)
                    return False
                if not revised_template:
                    continue
            qa_ok = await orch._run_skill_qa(run_id, mode=mode)
            await orch._append_repair_history(
                run_id=run_id,
                entry={
                    "round": repair_round,
                    "mode": mode.value,
                    "source": "latest_artifacts",
                    "qa_passed": qa_ok,
                },
            )
            await orch._publish(
                run_id,
                EventType.REPAIR_ROUND_COMPLETED,
                {
                    "round": repair_round,
                    "mode": mode.value,
                    "qa_passed": qa_ok,
                    "source": "latest_artifacts",
                },
            )
            if qa_ok:
                return True
        return False

    async def revise_scratch_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        if run is None or run.outline is None:
            return False
        effective_template_style = orch._resolved_template_style(run)
        if orch._use_agentic_engine():
            slides_dir = Path(run.artifact_dir) / "slides"
            for slide in sorted(run.slides, key=lambda x: x.slide_no):
                node = run.outline.nodes[slide.slide_no - 1]
                rule_issues = forced_issues or run.qa_report.get("issues", [])
                slide_plan = orch._build_slide_plan(node=node, design=design, slide_no=slide.slide_no)
                orch._apply_visual_policy_to_slide_plan(
                    slide_plan=slide_plan,
                    page_type=node.page_type,
                    visual_policy=run.input.visual_policy,
                )
                slide_plan["api_contract"] = dict(orch._js_api_contract)
                assets = await orch._prepare_scratch_visual_assets(
                    run=run,
                    node=node,
                    slide_no=slide.slide_no,
                    slide_plan=slide_plan,
                    slides_dir=slides_dir,
                )
                if assets:
                    visual_plan = slide_plan.get("visual_plan") if isinstance(slide_plan.get("visual_plan"), dict) else {}
                    visual_plan = dict(visual_plan)
                    visual_plan["assets"] = assets
                    slide_plan["visual_plan"] = visual_plan
                slide_brief = orch._build_slide_brief(run=run, node=node, slide_no=slide.slide_no, slide_plan=slide_plan)
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
                            issues=[str(item) for item in rule_issues][:12],
                            failure_context=orch._build_slide_failure_context(
                                phase="polish.repair_js",
                                slide_js_path=Path(slide.js_path) if slide.js_path else None,
                                candidate_js=slide.js_code,
                                issues=[str(item) for item in rule_issues][:12],
                                diagnostics={"error_message": "qa polish requested"},
                            ),
                            visual_policy=run.input.visual_policy,
                            slide_plan=slide_plan,
                            repair_directives=[str(item) for item in rule_issues][:12],
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
                            "issues_last_round": [f"polish skipped: {orch._exception_reason(exc)}"],
                            "engine": orch.settings.generation_engine,
                            "repair_mode": "js_repair_skipped",
                        },
                    )
                    continue
                fixed_js, normalize_fixes = orch._normalize_generated_slide_js(
                    fixed_js,
                    slide_no=slide.slide_no,
                    node=node,
                    target_slide_count=run.input.target_slide_count,
                )
                auto_fixes: list[str] = []
                if orch.slide_auto_canonicalize:
                    fixed_js, auto_fixes = orch._auto_canonicalize_slide_js(
                        fixed_js,
                        slide_no=slide.slide_no,
                        node=node,
                        target_slide_count=run.input.target_slide_count,
                    )
                if normalize_fixes or auto_fixes:
                    await orch._publish(
                        run_id,
                        EventType.SLIDE_AUTO_FIX_APPLIED,
                        {
                            "slide_no": slide.slide_no,
                            "round": 0,
                            "candidate": 1,
                            "fixes": orch._dedupe_preserve_order(normalize_fixes + auto_fixes)[:24],
                        },
                    )
                fixed_js = orch._apply_local_js_guardrails(
                    js_code=fixed_js,
                    slide_no=slide.slide_no,
                    page_type=node.page_type,
                )
                citations = orch._normalize_citations(slide.citations or run.input.rag_source_ids, run.input.rag_source_ids, slide.slide_no)
                reviewed = self.extract_candidate_from_js(
                    js_code=fixed_js,
                    fallback_node=node,
                    citations=citations,
                )
                chart_plan = orch._build_chart_plan_from_bullets(
                    node=OutlineNode(
                        title=reviewed.title,
                        bullets=list(reviewed.bullets),
                        page_type=node.page_type,
                        layout_hint=reviewed.layout_hint or node.layout_hint,
                    ),
                    source_refs=citations,
                )
                slide_path = Path(run.artifact_dir) / "slides" / f"slide-{slide.slide_no:02d}.js"
                slide_path.write_text(fixed_js, encoding="utf-8")
                slide.js_code = fixed_js
                slide.citations = citations
                await orch._append_chart_truth_report(
                    run_id=run_id,
                    entry={
                        "slide_no": slide.slide_no,
                        "has_verified_data": chart_plan.has_verified_data,
                        "mode": chart_plan.mode,
                        "source": chart_plan.source,
                        "note": chart_plan.note,
                        "labels": chart_plan.labels,
                    },
                )
                await orch._append_quality_entry(
                    run_id=run_id,
                    entry={
                        "slide_no": slide.slide_no,
                        "passed_round": 1,
                        "issues_last_round": [str(item) for item in rule_issues],
                        "engine": orch.settings.generation_engine,
                        "repair_mode": "js_repair",
                    },
                )
            return True
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
                        "issues_last_round": [f"polish skipped: {orch._exception_reason(exc)}"],
                        "engine": orch.settings.generation_engine,
                        "repair_mode": "review_skipped",
                    },
                )
                continue
            chart_plan = orch._build_chart_plan_from_bullets(
                node=OutlineNode(
                    title=reviewed.title,
                    bullets=list(reviewed.bullets),
                    page_type=node.page_type,
                    layout_hint=reviewed.layout_hint or node.layout_hint,
                ),
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
            await orch._append_chart_truth_report(
                run_id=run_id,
                entry={
                    "slide_no": slide.slide_no,
                    "has_verified_data": chart_plan.has_verified_data,
                    "mode": chart_plan.mode,
                    "source": chart_plan.source,
                    "note": chart_plan.note,
                    "labels": chart_plan.labels,
                },
            )
        return True

    def extract_candidate_from_js(self, *, js_code: str, fallback_node: OutlineNode, citations: list[str]) -> GeneratedSlide:
        title = self.extract_js_string_field(js_code, "title") or fallback_node.title
        layout_hint = self.extract_js_string_field(js_code, "layoutHint") or fallback_node.layout_hint
        bullets = self.extract_js_array_field(js_code, "bullets")
        if not bullets:
            bullets = list(fallback_node.bullets)
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=list(citations),
            page_type=fallback_node.page_type,
            layout_hint=layout_hint,
        )

    def extract_js_string_field(self, js_code: str, field_name: str) -> str | None:
        match = re.search(rf"{re.escape(field_name)}\s*:\s*(['\"])(.*?)\1", js_code, flags=re.DOTALL)
        if not match:
            return None
        raw = match.group(2)
        try:
            return json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            return raw

    def extract_js_array_field(self, js_code: str, field_name: str) -> list[str]:
        match = re.search(rf"{re.escape(field_name)}\s*:\s*(\[[\s\S]*?\])\s*,", js_code)
        if not match:
            return []
        raw = match.group(1)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    def check_slide_content_rules(self, candidate: GeneratedSlide, node: OutlineNode) -> list[str]:
        issues: list[str] = []
        if not candidate.title.strip():
            issues.append("title is empty")
        if len(candidate.bullets) < 2 and node.page_type in {SlidePageType.CONTENT, SlidePageType.SUMMARY, SlidePageType.TOC}:
            issues.append("not enough bullet points")
        if candidate.page_type != node.page_type:
            issues.append(f"page_type mismatch expected={node.page_type.value} got={candidate.page_type.value}")
        allowed_layouts = allowed_layouts_for(node.page_type)
        if candidate.layout_hint and candidate.layout_hint not in allowed_layouts:
            issues.append(f"layout_hint invalid for {node.page_type.value}: {candidate.layout_hint}")
        return issues

