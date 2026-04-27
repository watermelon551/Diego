from __future__ import annotations

from typing import Any

from ..design.style_catalog import get_style_dna_by_id
from ..llm import GeneratedSlide, SlideSpec
from ..models import OutlineNode, RunRecord


def build_slide_brief(
    *,
    run: RunRecord,
    node: OutlineNode,
    slide_no: int,
    slide_plan: dict[str, Any],
) -> dict[str, Any]:
    report = run.research_report if isinstance(run.research_report, dict) else {}
    page_focus_raw = report.get("page_focus", [])
    page_focus_list = (
        [str(item).strip() for item in page_focus_raw if str(item).strip()]
        if isinstance(page_focus_raw, list)
        else []
    )
    design_notes_raw = report.get("design_notes", [])
    design_notes = (
        [str(item).strip() for item in design_notes_raw if str(item).strip()]
        if isinstance(design_notes_raw, list)
        else []
    )
    design_intent = (
        report.get("design_intent", {})
        if isinstance(report.get("design_intent", {}), dict)
        else {}
    )
    style_dna = get_style_dna_by_id(str(design_intent.get("style_dna_id", "")).strip())
    selected_focus = (
        page_focus_list[slide_no - 1] if 0 < slide_no <= len(page_focus_list) else ""
    )
    visual_plan = (
        slide_plan.get("visual_plan", {})
        if isinstance(slide_plan.get("visual_plan", {}), dict)
        else {}
    )
    assets = (
        visual_plan.get("assets", [])
        if isinstance(visual_plan.get("assets", []), list)
        else []
    )
    return {
        "audience": str(report.get("audience", "")).strip(),
        "purpose": str(report.get("purpose", "")).strip(),
        "tone": str(report.get("tone", "")).strip(),
        "narrative_arc": str(report.get("narrative_arc", "")).strip(),
        "style_intent": str(report.get("style_intent", "")).strip(),
        "design_intent": design_intent,
        "current_page_focus": selected_focus,
        "page_type": node.page_type.value,
        "layout": str(slide_plan.get("layout", "")),
        "design_notes": design_notes[:8],
        "assets": assets,
        "style_dna": (
            {
                "id": style_dna.id,
                "name": style_dna.name,
                "style_signature": style_dna.style_signature,
                "layout_family": style_dna.layout_family,
                "density_profile": style_dna.density_profile,
                "shape_language": style_dna.shape_language,
                "decoration_policy": style_dna.decoration_policy,
                "visual_strategy_profile": style_dna.visual_strategy_profile,
            }
            if style_dna is not None
            else {}
        ),
    }


def candidate_variant_specs(
    *, slide_no: int, round_no: int, worker_count: int, layout: str
) -> list[dict[str, Any]]:
    seeds = [
        {"composition": "balanced", "emphasis": "narrative", "density": "medium", "contrast": "high"},
        {"composition": "visual_heavy", "emphasis": "data", "density": "compact", "contrast": "high"},
        {"composition": "text_heavy", "emphasis": "explanation", "density": "airy", "contrast": "medium"},
        {"composition": "diagrammatic", "emphasis": "structure", "density": "medium", "contrast": "high"},
        {"composition": "storyboard", "emphasis": "progression", "density": "medium", "contrast": "medium"},
    ]
    variants: list[dict[str, Any]] = []
    for worker_idx in range(1, worker_count + 1):
        base = dict(seeds[(worker_idx - 1) % len(seeds)])
        base["worker"] = worker_idx
        base["round"] = round_no
        base["layout_anchor"] = layout
        base["seed"] = f"s{slide_no}-r{round_no}-w{worker_idx}-{layout}"
        variants.append(base)
    return variants


def fallback_research_brief(
    *, topic: str, template_style: str, target_slide_count: int
) -> dict[str, Any]:
    focus: list[str] = []
    for idx in range(1, target_slide_count + 1):
        if idx == 1:
            focus.append(f"{topic}: opening context and core claim")
        elif idx == target_slide_count:
            focus.append(f"{topic}: synthesis, decisions, and next steps")
        else:
            focus.append(
                f"{topic}: section {idx} with concrete evidence and visual takeaway"
            )
    return {
        "audience": "general audience",
        "purpose": f"explain {topic} clearly with actionable insights",
        "tone": "professional and concise",
        "narrative_arc": "background -> key points -> evidence -> practical takeaways",
        "page_focus": focus,
        "design_notes": [
            f"Keep visual language consistent with template_style={template_style}.",
            "Enforce strong title/body hierarchy and left-aligned body text.",
            "Ensure every content page has a meaningful non-text visual anchor.",
        ],
        "style_intent": template_style,
        "effective_template_style": template_style,
    }


def slide_spec_from_generated(*, generated: GeneratedSlide, node: OutlineNode) -> SlideSpec:
    return SlideSpec(
        title=generated.title or node.title,
        subtitle="",
        bullets=list(generated.bullets or node.bullets),
        page_type=node.page_type,
        layout_hint=generated.layout_hint or node.layout_hint,
        visual_kind="shape",
        emphasis="",
        citations=list(generated.citations),
    )


def generated_from_slide_spec(*, spec: SlideSpec, node: OutlineNode) -> GeneratedSlide:
    return GeneratedSlide(
        title=spec.title or node.title,
        bullets=list(spec.bullets or node.bullets),
        citations=list(spec.citations),
        page_type=node.page_type,
        layout_hint=spec.layout_hint or node.layout_hint,
    )
