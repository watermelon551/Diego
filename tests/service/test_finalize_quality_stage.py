from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.models import (
    CreateRunRequest,
    EventType,
    GenerationMode,
    RunRecord,
    RunStatus,
)
from service.run.stages import FinalizeQualityStage


class _DummyStore:
    def __init__(self, run: RunRecord) -> None:
        self._run = run

    async def get_run(self, _run_id: str) -> RunRecord:
        return self._run

    async def update_run(self, _run_id: str, mutator) -> None:
        mutator(self._run)


class _DummyQualityEngine:
    async def complete_post_compile_quality(self, **kwargs):
        return True


@pytest.mark.anyio
async def test_finalize_quality_timeout_with_ready_pptx_should_degrade_to_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pptx_path = tmp_path / "presentation.pptx"
    pptx_path.write_bytes(b"pptx")
    run = RunRecord(
        run_id="r-timeout-ok",
        trace_id="t-timeout-ok",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(topic="topic", project_id="p"),
        artifact_dir=str(tmp_path / "artifacts"),
        pptx_path=str(pptx_path),
    )
    orch = SimpleNamespace(
        settings=SimpleNamespace(qa_finalize_timeout_sec=1),
        quality_engine=_DummyQualityEngine(),
        store=_DummyStore(run),
        _publish=AsyncMock(),
        _fail_run=AsyncMock(),
        _finalize_run_success=AsyncMock(),
    )
    stage = FinalizeQualityStage(orch)

    async def _raise_timeout(awaitable, *args, **kwargs):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("service.run.stages.asyncio.wait_for", _raise_timeout)

    ok = await stage.execute(
        run_id="r-timeout-ok",
        mode=GenerationMode.SCRATCH,
        design=None,
        from_stage="COMPILING",
        success_reason="compile+qa",
    )

    assert ok is True
    assert orch._fail_run.await_count == 0
    assert orch._finalize_run_success.await_count == 1
    assert run.qa_report.get("degraded") is True
    assert run.qa_report.get("degraded_reason") == "FINALIZE_TIMEOUT"
    assert orch._publish.await_count == 1
    publish_args = orch._publish.await_args_list[0].args
    assert publish_args[1] == EventType.QA_COMPLETED


@pytest.mark.anyio
async def test_finalize_quality_timeout_without_pptx_should_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = RunRecord(
        run_id="r-timeout-fail",
        trace_id="t-timeout-fail",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(topic="topic", project_id="p"),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    orch = SimpleNamespace(
        settings=SimpleNamespace(qa_finalize_timeout_sec=1),
        quality_engine=_DummyQualityEngine(),
        store=_DummyStore(run),
        _publish=AsyncMock(),
        _fail_run=AsyncMock(),
        _finalize_run_success=AsyncMock(),
    )
    stage = FinalizeQualityStage(orch)

    async def _raise_timeout(awaitable, *args, **kwargs):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("service.run.stages.asyncio.wait_for", _raise_timeout)

    ok = await stage.execute(
        run_id="r-timeout-fail",
        mode=GenerationMode.SCRATCH,
        design=None,
        from_stage="COMPILING",
        success_reason="compile+qa",
    )

    assert ok is False
    assert orch._fail_run.await_count == 1
    assert orch._finalize_run_success.await_count == 0
