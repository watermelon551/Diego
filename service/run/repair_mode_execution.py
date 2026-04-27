from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..design.skill_profile import DesignProfile
from ..models import GenerationMode
from .types import TemplateLayoutConflictError, TemplateSlotMappingError


@dataclass(frozen=True)
class RepairModeExecutionResult:
    advanced: bool
    terminal_failure: bool = False


async def execute_repair_round_mode(
    *,
    orchestrator: Any,
    run_id: str,
    mode: GenerationMode,
    design: DesignProfile,
    forced_issues: list[str] | None,
    revise_scratch_slides: Callable[..., Awaitable[bool]],
) -> RepairModeExecutionResult:
    if mode == GenerationMode.SCRATCH:
        revised = await revise_scratch_slides(
            run_id=run_id,
            design=design,
            forced_issues=forced_issues,
        )
        if not revised:
            return RepairModeExecutionResult(advanced=False)
        compiled = await orchestrator._compile_scratch_slides(run_id)
        return RepairModeExecutionResult(advanced=compiled)

    try:
        revised_template = await orchestrator._revise_template_slides(
            run_id=run_id,
            design=design,
            forced_issues=forced_issues,
        )
    except TemplateSlotMappingError:
        await orchestrator._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_SLOT_UNMAPPED", retryable=False)
        return RepairModeExecutionResult(advanced=False, terminal_failure=True)
    except TemplateLayoutConflictError:
        await orchestrator._fail_run(run_id, "SLIDES_GENERATING", "TEMPLATE_LAYOUT_CONFLICT", retryable=False)
        return RepairModeExecutionResult(advanced=False, terminal_failure=True)

    return RepairModeExecutionResult(advanced=bool(revised_template))
