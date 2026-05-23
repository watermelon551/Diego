from __future__ import annotations

from pathlib import Path
from typing import Any

from ...design.skill_profile import DesignProfile
from ...llm import GeneratedSlide
from ...models import EventType, OutlineNode, RunRecord, SlideArtifact
from ..template_apply_reporting import (
    build_chart_truth_checked_payload,
    build_slot_mapping_completed_payload,
    build_slot_mapping_entry,
    build_template_chart_report,
    build_template_fidelity_payload,
    build_template_layout_completed_payload,
    build_template_layout_report,
    build_template_mapping_report,
)
from ..types import TemplateLayoutConflictError, TemplateSlotMappingError


class CompileTemplateApplyMixin:
    orch: Any

    async def apply_template_nodes_once(
        self,
        *,
        run_id: str,
        unpacked: Path,
        design: DesignProfile,
        use_review: bool,
        forced_issues: list[str] | None,
    ) -> list[SlideArtifact] | None:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        if run is None or run.outline is None:
            return None
        effective_template_style = orch._resolved_template_style(run)
        slide_files = orch._rebuild_template_structure(
            unpacked=unpacked, target_count=len(run.outline.nodes)
        )
        _, _, _, _, _, template_slides_dir, template_compile_js, _ = self.template_work_paths(
            Path(run.artifact_dir)
        )
        template_slides_dir.mkdir(parents=True, exist_ok=True)
        (template_slides_dir / "output").mkdir(parents=True, exist_ok=True)

        artifacts: list[SlideArtifact] = []
        mapping_report: dict[str, Any] = build_template_mapping_report()
        chart_report: dict[str, Any] = build_template_chart_report()
        layout_report: dict[str, Any] = build_template_layout_report()
        for idx, slide_xml in enumerate(slide_files, start=1):
            if idx > len(run.outline.nodes):
                break
            base_node = run.outline.nodes[idx - 1]
            node_for_apply = base_node
            citations = orch._normalize_citations([], run.input.rag_source_ids, idx)
            if use_review:
                candidate = self.extract_candidate_from_template_slide(
                    unpacked=unpacked,
                    slide_xml=slide_xml,
                    fallback_node=base_node,
                    citations=citations,
                )
                reviewed = await orch._call_llm_with_timeout_retry(
                    run_id=run_id,
                    phase=f"template.slide.{idx}.review",
                    action=lambda: orch.llm_client.review_slide(
                        topic=run.input.topic,
                        template_style=effective_template_style,
                        slide_no=idx,
                        target_slide_count=run.input.target_slide_count,
                        outline_node=base_node,
                        candidate=candidate,
                        rule_violations=forced_issues or run.qa_report.get("issues", []),
                    ),
                )
                node_for_apply = OutlineNode(
                    title=reviewed.title,
                    bullets=reviewed.bullets,
                    page_type=base_node.page_type,
                    layout_hint=reviewed.layout_hint or base_node.layout_hint,
                )
                citations = orch._normalize_citations(
                    reviewed.citations, run.input.rag_source_ids, idx
                )

            slot_graph = orch._build_slot_graph(slide_xml=slide_xml, slide_no=idx)
            mapping = orch._plan_slot_mapping(slot_graph=slot_graph)
            mapping_entry = build_slot_mapping_entry(slide_no=idx, slots=mapping["slots"])
            missing = mapping_entry["missing_required"]
            mapping_report["slides"].append(mapping_entry)
            await orch._publish(
                run_id,
                EventType.SLOT_MAPPING_COMPLETED,
                build_slot_mapping_completed_payload(mapping_entry),
            )
            if missing:
                mapping_report["passed"] = False
                mapping_report["unmapped_required"].extend(
                    [{"slide_no": idx, **item} for item in missing]
                )
                await orch.store.update_run(
                    run_id,
                    lambda r: setattr(r, "template_mapping_report", mapping_report),
                )
                raise TemplateSlotMappingError(slide_no=idx, missing_slots=missing)

            chart_plan = orch._build_chart_plan_from_bullets(
                node=node_for_apply,
                source_refs=citations,
            )
            context = orch._build_asset_search_context(
                run=run,
                node=node_for_apply,
                slide_no=idx,
                slide_plan={"layout": node_for_apply.layout_hint or base_node.layout_hint or ""},
            )
            orch._push_asset_search_context(context)
            try:
                semantic_report = orch._rewrite_template_slide_semantics(
                    unpacked=unpacked,
                    slide_xml=slide_xml,
                    node=node_for_apply,
                    slide_no=idx,
                    chart_plan=chart_plan,
                )
            finally:
                orch._pop_asset_search_context()
            layout_entry = semantic_report.get("layout")
            if isinstance(layout_entry, dict):
                layout_report["slides"].append(layout_entry)
                await orch._publish(
                    run_id,
                    EventType.TEMPLATE_LAYOUT_REFLOW_COMPLETED,
                    build_template_layout_completed_payload(layout_entry),
                )
                await orch._publish(
                    run_id,
                    EventType.TEMPLATE_FIDELITY_CHECKED,
                    build_template_fidelity_payload(layout_entry),
                )
                if not bool(layout_entry.get("passed", False)):
                    layout_report["passed"] = False
                    await orch.store.update_run(
                        run_id,
                        lambda r: setattr(r, "template_layout_report", layout_report),
                    )
                    raise TemplateLayoutConflictError(
                        slide_no=idx,
                        issues=list(layout_entry.get("issues_after", [])),
                    )
            if semantic_report.get("chart"):
                chart_report["slides"].append(
                    {"slide_no": idx, **semantic_report["chart"]}
                )
                if not semantic_report["chart"].get("has_verified_data"):
                    chart_report["passed"] = False
                await orch._publish(
                    run_id,
                    EventType.CHART_TRUTH_CHECKED,
                    build_chart_truth_checked_payload(
                        slide_no=idx, chart_entry=semantic_report["chart"]
                    ),
                )

            generated = GeneratedSlide(
                title=node_for_apply.title,
                bullets=list(node_for_apply.bullets),
                citations=list(citations),
                page_type=base_node.page_type,
                layout_hint=node_for_apply.layout_hint,
            )
            js_code = orch._render_skill_slide_js(
                slide_no=idx,
                total=run.input.target_slide_count,
                node=base_node,
                generated=generated,
                design=design,
                chart_plan=chart_plan,
                outline_nodes=list(run.outline.nodes) if run.outline is not None else [],
            )
            slide_path = template_slides_dir / f"slide-{idx:02d}.js"
            slide_path.write_text(js_code, encoding="utf-8")
            artifacts.append(
                SlideArtifact(
                    slide_no=idx,
                    js_path=str(slide_path),
                    js_code=js_code,
                    status="ok",
                    citations=list(citations),
                )
            )

        template_compile_js.write_text(
            orch._build_compile_script(total=len(artifacts), theme=design.theme),
            encoding="utf-8",
        )

        def apply_reports(r: RunRecord) -> None:
            r.template_mapping_report = mapping_report
            r.chart_truth_report = chart_report
            r.template_layout_report = layout_report

        await orch.store.update_run(run_id, apply_reports)
        orch._cleanup_orphan_media(unpacked=unpacked)
        return artifacts
