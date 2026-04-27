from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.models import GenerationMode
from service.run.repair_mode_execution import execute_repair_round_mode
from service.run.types import TemplateSlotMappingError


@pytest.mark.anyio
async def test_execute_repair_round_mode_runs_scratch_revision_then_compile() -> None:
    orchestrator = SimpleNamespace(
        _compile_scratch_slides=AsyncMock(return_value=True),
        _revise_template_slides=AsyncMock(),
        _fail_run=AsyncMock(),
    )
    revise_scratch_slides = AsyncMock(return_value=True)

    result = await execute_repair_round_mode(
        orchestrator=orchestrator,
        run_id="run-1",
        mode=GenerationMode.SCRATCH,
        design=SimpleNamespace(),
        forced_issues=["issue"],
        revise_scratch_slides=revise_scratch_slides,
    )

    assert result.advanced is True
    assert result.terminal_failure is False
    revise_scratch_slides.assert_awaited_once()
    orchestrator._compile_scratch_slides.assert_awaited_once_with("run-1")
    orchestrator._revise_template_slides.assert_not_awaited()
    orchestrator._fail_run.assert_not_awaited()


@pytest.mark.anyio
async def test_execute_repair_round_mode_returns_non_terminal_when_scratch_compile_fails() -> None:
    orchestrator = SimpleNamespace(
        _compile_scratch_slides=AsyncMock(return_value=False),
        _revise_template_slides=AsyncMock(),
        _fail_run=AsyncMock(),
    )
    revise_scratch_slides = AsyncMock(return_value=True)

    result = await execute_repair_round_mode(
        orchestrator=orchestrator,
        run_id="run-2",
        mode=GenerationMode.SCRATCH,
        design=SimpleNamespace(),
        forced_issues=None,
        revise_scratch_slides=revise_scratch_slides,
    )

    assert result.advanced is False
    assert result.terminal_failure is False
    orchestrator._fail_run.assert_not_awaited()


@pytest.mark.anyio
async def test_execute_repair_round_mode_fails_fast_for_template_mapping_errors() -> None:
    orchestrator = SimpleNamespace(
        _compile_scratch_slides=AsyncMock(),
        _revise_template_slides=AsyncMock(
            side_effect=TemplateSlotMappingError(slide_no=1, missing_slots=[{"slot_type": "unknown"}])
        ),
        _fail_run=AsyncMock(),
    )
    revise_scratch_slides = AsyncMock()

    result = await execute_repair_round_mode(
        orchestrator=orchestrator,
        run_id="run-3",
        mode=GenerationMode.TEMPLATE,
        design=SimpleNamespace(),
        forced_issues=["issue"],
        revise_scratch_slides=revise_scratch_slides,
    )

    assert result.advanced is False
    assert result.terminal_failure is True
    revise_scratch_slides.assert_not_awaited()
    orchestrator._compile_scratch_slides.assert_not_awaited()
    orchestrator._fail_run.assert_awaited_once_with(
        "run-3",
        "SLIDES_GENERATING",
        "TEMPLATE_SLOT_UNMAPPED",
        retryable=False,
    )
