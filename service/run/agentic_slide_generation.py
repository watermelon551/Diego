from __future__ import annotations

from pathlib import Path
from typing import Any

from ..design.skill_profile import DesignProfile
from ..models import OutlineNode, SlideArtifact
from .agentic_slide_finalization import finalize_agentic_slide
from .agentic_slide_candidate_rounds import run_agentic_candidate_rounds
from .agentic_slide_preparation import prepare_agentic_slide_context
from .slide_candidate_decisions import (
    is_missing_output,
)
from .slide_candidate_finalize import (
    build_missing_output_details,
)
from .types import SlideGenerationError


async def generate_agentic_slide(
    orch: Any,
    *,
    run_id: str,
    slide_no: int,
    node: OutlineNode,
    design: DesignProfile,
    slides_dir: Path,
) -> SlideArtifact:
    context = await prepare_agentic_slide_context(
        orch,
        run_id=run_id,
        slide_no=slide_no,
        node=node,
        design=design,
        slides_dir=slides_dir,
    )
    await run_agentic_candidate_rounds(
        orch,
        run_id=run_id,
        slide_no=slide_no,
        node=node,
        design=design,
        context=context,
    )
    if is_missing_output(
        round_passed=context.candidate_state.round_passed,
        output_exists=context.slide_path.exists(),
    ):
        raise SlideGenerationError(
            slide_no=slide_no,
            phase="candidate.missing_output",
            reason="single-candidate generation produced no accepted slide",
            round_no=context.hard_round_limit,
            details=build_missing_output_details(state=context.candidate_state),
        )
    return await finalize_agentic_slide(
        orch,
        run_id=run_id,
        slide_no=slide_no,
        run=context.run,
        slide_path=context.slide_path,
        candidate_state=context.candidate_state,
    )
