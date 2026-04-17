from __future__ import annotations

import asyncio
from pathlib import Path

from service.models import ConfirmOutlineRequest, CreateRunRequest, EventType, GenerationMode, OutlineDocument, OutlineNode, RunRecord, RunStatus
from service.run.kernel import RunKernel
from service.run.orchestrator import RunOrchestrator
from service.infra.store import RunStore

from tests.support.service_flow_shared import MockLLMClient, make_settings


class _NoopStage:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, ctx) -> None:
        self.executed.append(ctx.run_id)


def _make_orchestrator(tmp_path: Path) -> RunOrchestrator:
    return RunOrchestrator(
        store=RunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )


def test_kernel_create_run_should_create_outline_drafting_run(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    outline_stage = _NoopStage()
    kernel = RunKernel(
        orchestrator=orch,
        outline_stage=outline_stage,
        scratch_stage=_NoopStage(),
        template_stage=_NoopStage(),
    )

    async def scenario() -> None:
        summary = await kernel.create_run(CreateRunRequest(topic="Kernel", project_id="p1"))
        assert summary.status == RunStatus.OUTLINE_DRAFTING
        run = await orch.store.get_run(summary.run_id)
        assert run is not None
        assert run.status == RunStatus.OUTLINE_DRAFTING
        assert run.trace_id == summary.trace_id

    asyncio.run(scenario())


def test_kernel_confirm_outline_should_keep_gate_and_emit_update_event(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    kernel = orch._kernel
    run = RunRecord(
        run_id="r-confirm",
        trace_id="t-confirm",
        status=RunStatus.AWAITING_OUTLINE_CONFIRM,
        input=CreateRunRequest(topic="Kernel Confirm", project_id="p2", generation_mode=GenerationMode.SCRATCH),
        artifact_dir=str(tmp_path / "artifacts" / "r-confirm"),
        outline=OutlineDocument(
            version=1,
            summary="draft",
            nodes=[OutlineNode(title="One", bullets=["a"])],
        ),
    )
    asyncio.run(orch.store.add_run(run))

    updated_outline = OutlineDocument(
        version=1,
        summary="updated",
        nodes=[OutlineNode(title="Updated", bullets=["b"])],
    )

    async def scenario() -> None:
        summary = await kernel.confirm_outline(
            "r-confirm",
            ConfirmOutlineRequest(
                approved=False,
                outline=updated_outline,
                base_version=1,
                change_reason="edit",
            ),
        )
        assert summary is not None
        assert summary.status == RunStatus.AWAITING_OUTLINE_CONFIRM
        detail = await kernel.get_run_detail("r-confirm")
        assert detail is not None
        assert detail.outline is not None
        assert detail.outline.version == 2
        assert detail.events[-1].event == EventType.OUTLINE_UPDATED

    asyncio.run(scenario())


def test_kernel_fail_and_finalize_should_update_terminal_state(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    kernel = orch._kernel
    run = RunRecord(
        run_id="r-final",
        trace_id="t-final",
        status=RunStatus.COMPILING,
        input=CreateRunRequest(topic="Kernel Finalize", project_id="p3"),
        artifact_dir=str(tmp_path / "artifacts" / "r-final"),
    )
    asyncio.run(orch.store.add_run(run))

    async def scenario() -> None:
        await kernel.fail_run("r-final", "COMPILING", "QA_FAILED", retryable=False, error_details={"reason": "x"})
        detail = await kernel.get_run_detail("r-final")
        assert detail is not None
        assert detail.status == RunStatus.FAILED
        assert detail.error_code == "QA_FAILED"
        assert detail.failed_stage == "COMPILING"
        assert detail.events[-2].event == EventType.RUN_FAILED
        assert detail.events[-1].event == EventType.RUN_FINALIZED

        await orch.store.update_run("r-final", lambda r: setattr(r, "status", RunStatus.COMPILING))
        await kernel.finalize_run_success("r-final", from_stage="COMPILING", reason="ok")
        detail = await kernel.get_run_detail("r-final")
        assert detail is not None
        assert detail.status == RunStatus.SUCCEEDED
        assert detail.error_code is None
        assert detail.events[-1].event == EventType.RUN_FINALIZED

    asyncio.run(scenario())
