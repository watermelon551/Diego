from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..design.skill_profile import DesignProfile
from ..models import EventType, OutlineNode, RunRecord
from .slide_candidate_decisions import resolve_round_limits
from .slide_candidate_state import AgenticSlideCandidateState


@dataclass
class PreparedAgenticSlideContext:
    run: RunRecord
    effective_template_style: str
    slide_plan: dict[str, Any]
    slide_brief: dict[str, Any]
    slide_path: Path
    candidate_path: Path
    candidate_state: AgenticSlideCandidateState
    soft_round_limit: int
    hard_round_limit: int
    compile_failure_markers: tuple[str, ...]


async def prepare_agentic_slide_context(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    node: OutlineNode,
    design: DesignProfile,
    slides_dir: Path,
) -> PreparedAgenticSlideContext:
    run = await orch.store.get_run(run_id)
    assert run is not None
    effective_template_style = orch._resolved_template_style(run)
    style_dna_id = orch._resolved_style_dna_id(run)
    slide_plan = orch._build_slide_plan(node=node, design=design, slide_no=slide_no, style_dna_id=style_dna_id)
    orch._apply_visual_policy_to_slide_plan(
        slide_plan=slide_plan,
        page_type=node.page_type,
        visual_policy=run.input.visual_policy,
    )
    slide_plan["api_contract"] = dict(orch._js_api_contract)
    assets = await orch._prepare_scratch_visual_assets(
        run=run,
        node=node,
        slide_no=slide_no,
        slide_plan=slide_plan,
        slides_dir=slides_dir,
    )
    if assets:
        visual_plan = slide_plan.get("visual_plan") if isinstance(slide_plan.get("visual_plan"), dict) else {}
        visual_plan = dict(visual_plan)
        visual_plan["assets"] = assets
        slide_plan["visual_plan"] = visual_plan
    slide_brief = orch._build_slide_brief(run=run, node=node, slide_no=slide_no, slide_plan=slide_plan)
    await orch._publish(
        run_id,
        EventType.SLIDE_PLAN_COMPLETED,
        {
            "slide_no": slide_no,
            "layout": slide_plan.get("layout"),
            "visual_policy": run.input.visual_policy.value,
            "visual_plan": slide_plan.get("visual_plan", {}),
            "constraints": slide_plan.get("constraints", {}),
            "style_dna_id": style_dna_id or "",
        },
    )
    await orch._publish(
        run_id,
        EventType.SLIDE_CODEGEN_STARTED,
        {"slide_no": slide_no, "engine": orch.settings.generation_engine},
    )
    soft_round_limit, hard_round_limit = resolve_round_limits(
        max_slide_repair_rounds=orch.max_slide_repair_rounds
    )
    return PreparedAgenticSlideContext(
        run=run,
        effective_template_style=effective_template_style,
        slide_plan=slide_plan,
        slide_brief=slide_brief,
        slide_path=slides_dir / f"slide-{slide_no:02d}.js",
        candidate_path=slides_dir / f"slide-{slide_no:02d}-cand-01.js",
        candidate_state=AgenticSlideCandidateState(),
        soft_round_limit=soft_round_limit,
        hard_round_limit=hard_round_limit,
        compile_failure_markers=(
            "missing export contract",
            "createslide signature invalid",
            "createslide must be synchronous",
            "addtext call signature invalid",
            "addshape call signature invalid",
            "preview compile failed",
            "preview skipped due to fatal contract issue",
            "preview pptx missing",
            "forbidden api detected",
            "llm_output_not_executable",
            "jsondecodeerror",
        ),
    )
