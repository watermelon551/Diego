from __future__ import annotations

from pathlib import Path
from typing import Any

from .....design.skill_profile import DesignProfile


class AgenticScratchRevisionSlidePlanMixin:
    orch: Any

    async def _prepare_agentic_repair_slide_plan(
        self,
        *,
        run: Any,
        slide: Any,
        node: Any,
        design: DesignProfile,
        slides_dir: Path,
    ) -> dict[str, Any]:
        orch = self.orch
        slide_plan = orch._build_slide_plan(
            node=node,
            design=design,
            slide_no=slide.slide_no,
            style_dna_id=orch._resolved_style_dna_id(run),
        )
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
            visual_plan = (
                slide_plan.get("visual_plan")
                if isinstance(slide_plan.get("visual_plan"), dict)
                else {}
            )
            visual_plan = dict(visual_plan)
            visual_plan["assets"] = assets
            slide_plan["visual_plan"] = visual_plan
        return slide_plan
