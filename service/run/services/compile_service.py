from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from ...design.skill_profile import DesignProfile
from ...llm import GeneratedSlide
from ...models import EventType, OutlineNode, RunRecord, SlideArtifact
from ..types import TemplateAssetError, TemplateLayoutConflictError, TemplateSlotMappingError


class CompileService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    def template_work_paths(self, artifact_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
        template_dir = artifact_dir / "template_edit"
        work_template = template_dir / "template.pptx"
        template_md = template_dir / "template.md"
        unpacked = template_dir / "unpacked"
        edited = template_dir / "edited.pptx"
        template_slides_dir = artifact_dir / "template_slides"
        template_compile_js = template_slides_dir / "compile.js"
        template_compiled_pptx = template_slides_dir / "output" / "presentation.pptx"
        return template_dir, work_template, template_md, unpacked, edited, template_slides_dir, template_compile_js, template_compiled_pptx

    def pack_template_unpacked(self, *, unpacked: Path, edited: Path) -> None:
        with ZipFile(edited, "w", compression=ZIP_DEFLATED) as zout:
            for file in unpacked.rglob("*"):
                if file.is_file():
                    arc = file.relative_to(unpacked).as_posix()
                    zout.write(file, arc)

    async def compile_template_js(self, *, template_slides_dir: Path) -> bool:
        orch = self.orch
        result = await asyncio.to_thread(
            orch.subprocess.run,
            ["node", "compile.js"],
            cwd=template_slides_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return result.returncode == 0

    async def compile_scratch_slides(self, run_id: str) -> bool:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        if run is None:
            return False
        compile_res = await asyncio.to_thread(
            orch.subprocess.run,
            ["node", "compile.js"],
            cwd=Path(run.artifact_dir) / "slides",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return compile_res.returncode == 0

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
        slide_files = orch._rebuild_template_structure(unpacked=unpacked, target_count=len(run.outline.nodes))
        _, _, _, _, _, template_slides_dir, template_compile_js, _ = self.template_work_paths(Path(run.artifact_dir))
        template_slides_dir.mkdir(parents=True, exist_ok=True)
        (template_slides_dir / "output").mkdir(parents=True, exist_ok=True)

        artifacts: list[SlideArtifact] = []
        mapping_report: dict[str, Any] = {"mode": "template", "slides": [], "unmapped_required": [], "passed": True}
        chart_report: dict[str, Any] = {"slides": [], "passed": True}
        layout_report: dict[str, Any] = {"slides": [], "passed": True}
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
                citations = orch._normalize_citations(reviewed.citations, run.input.rag_source_ids, idx)

            slot_graph = orch._build_slot_graph(slide_xml=slide_xml, slide_no=idx)
            mapping = orch._plan_slot_mapping(slot_graph=slot_graph)
            missing = [item for item in mapping["slots"] if item["required"] and not item["mapped"]]
            mapping_entry = {
                "slide_no": idx,
                "slot_count": len(mapping["slots"]),
                "mapped_count": sum(1 for item in mapping["slots"] if item["mapped"]),
                "missing_required": missing,
                "slots": mapping["slots"],
            }
            mapping_report["slides"].append(mapping_entry)
            await orch._publish(
                run_id,
                EventType.SLOT_MAPPING_COMPLETED,
                {
                    "slide_no": idx,
                    "mapped_count": mapping_entry["mapped_count"],
                    "slot_count": mapping_entry["slot_count"],
                    "missing_required": missing,
                },
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
            semantic_report = orch._rewrite_template_slide_semantics(
                unpacked=unpacked,
                slide_xml=slide_xml,
                node=node_for_apply,
                slide_no=idx,
                chart_plan=chart_plan,
            )
            layout_entry = semantic_report.get("layout")
            if isinstance(layout_entry, dict):
                layout_report["slides"].append(layout_entry)
                await orch._publish(
                    run_id,
                    EventType.TEMPLATE_LAYOUT_REFLOW_COMPLETED,
                    {
                        "slide_no": idx,
                        "box_count": int(layout_entry.get("box_count", 0)),
                        "moved_count": int(layout_entry.get("moved_count", 0)),
                        "issues_before_count": int(layout_entry.get("issues_before_count", 0)),
                        "issues_after_count": int(layout_entry.get("issues_after_count", 0)),
                        "passed": bool(layout_entry.get("passed", False)),
                    },
                )
                await orch._publish(
                    run_id,
                    EventType.TEMPLATE_FIDELITY_CHECKED,
                    {
                        "slide_no": idx,
                        "fidelity_score": int(layout_entry.get("fidelity_score", 0)),
                        "passed": bool(layout_entry.get("passed", False)),
                    },
                )
                if not bool(layout_entry.get("passed", False)):
                    layout_report["passed"] = False
                    await orch.store.update_run(
                        run_id,
                        lambda r: setattr(r, "template_layout_report", layout_report),
                    )
                    raise TemplateLayoutConflictError(slide_no=idx, issues=list(layout_entry.get("issues_after", [])))
            if semantic_report.get("chart"):
                chart_report["slides"].append({"slide_no": idx, **semantic_report["chart"]})
                if not semantic_report["chart"].get("has_verified_data"):
                    chart_report["passed"] = False
                await orch._publish(
                    run_id,
                    EventType.CHART_TRUTH_CHECKED,
                    {
                        "slide_no": idx,
                        "has_verified_data": semantic_report["chart"].get("has_verified_data", False),
                        "mode": semantic_report["chart"].get("mode", "none"),
                        "source": semantic_report["chart"].get("source", ""),
                    },
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

    async def revise_template_slides(self, *, run_id: str, design: DesignProfile, forced_issues: list[str] | None) -> bool:
        orch = self.orch
        run = await orch.store.get_run(run_id)
        if run is None:
            return False
        _, _, _, unpacked, edited, template_slides_dir, template_compile_js, _ = self.template_work_paths(Path(run.artifact_dir))
        if not unpacked.exists():
            return False
        try:
            artifacts = await self.apply_template_nodes_once(
                run_id=run_id,
                unpacked=unpacked,
                design=design,
                use_review=True,
                forced_issues=forced_issues,
            )
        except TemplateAssetError:
            return False
        if not artifacts:
            return False
        self.pack_template_unpacked(unpacked=unpacked, edited=edited)
        compiled = await self.compile_template_js(template_slides_dir=template_slides_dir)
        if not compiled:
            return False

        def apply_compile(r: RunRecord) -> None:
            r.pptx_path = str(edited)
            r.compile_js_path = str(template_compile_js)
            r.stage_timings.compile_ms = max(1, r.stage_timings.compile_ms)
            r.slides = artifacts
            r.citation_map = {item.slide_no: list(item.citations) for item in artifacts}

        await orch.store.update_run(run_id, apply_compile)
        await orch._publish(run_id, EventType.COMPILE_COMPLETED, {"file": str(edited), "mode": "template-repair"})
        return True

    def extract_candidate_from_template_slide(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        fallback_node: OutlineNode,
        citations: list[str],
    ) -> GeneratedSlide:
        orch = self.orch
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        placeholder_re = re.compile(r"(placeholder|lorem|ipsum|xxxx|template|caption|insert)", flags=re.IGNORECASE)
        raw_texts = [orch._xml_unescape(item).strip() for item in re.findall(r"<a:t>(.*?)</a:t>", content, flags=re.DOTALL)]
        texts = [item for item in raw_texts if item and not placeholder_re.search(item)]
        chart_texts = self.extract_related_chart_texts(unpacked=unpacked, slide_xml=slide_xml)
        title = texts[0] if texts else fallback_node.title
        bullets = [item for item in texts[1:] if item != title]
        for item in chart_texts:
            if item and item != title and item not in bullets:
                bullets.append(item)
        if not bullets:
            bullets = list(fallback_node.bullets)
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=list(citations),
            page_type=fallback_node.page_type,
            layout_hint=fallback_node.layout_hint,
        )

    def extract_related_chart_texts(self, *, unpacked: Path, slide_xml: Path) -> list[str]:
        orch = self.orch
        rels_path = slide_xml.parent / "_rels" / f"{slide_xml.name}.rels"
        if not rels_path.exists():
            return []
        rels_text = rels_path.read_text(encoding="utf-8", errors="ignore")
        results: list[str] = []
        for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
            attrs = orch._parse_xml_attrs(tag)
            rel_type = attrs.get("Type", "")
            target = attrs.get("Target", "")
            if not rel_type.endswith("/chart") or not target:
                continue
            chart_path = (slide_xml.parent / target).resolve()
            try:
                chart_path.relative_to(unpacked.resolve())
            except ValueError:
                continue
            if not chart_path.exists():
                continue
            chart_xml = chart_path.read_text(encoding="utf-8", errors="ignore")
            for text in re.findall(r"<(?:a:t|c:v)>(.*?)</(?:a:t|c:v)>", chart_xml, flags=re.DOTALL):
                normalized = orch._xml_unescape(text).strip()
                if normalized and normalized not in results:
                    results.append(normalized)
        return results
