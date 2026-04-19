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


class _LoopBoundRunStore(RunStore):
    def __init__(self, base_dir: Path) -> None:
        super().__init__(base_dir=base_dir)
        self._owner_loop_id: int | None = None

    async def add_run(self, run: RunRecord) -> None:
        loop_id = id(asyncio.get_running_loop())
        if self._owner_loop_id is None:
            self._owner_loop_id = loop_id
        await super().add_run(run)

    async def get_run(self, run_id: str) -> RunRecord | None:
        loop_id = id(asyncio.get_running_loop())
        if self._owner_loop_id is not None and self._owner_loop_id != loop_id:
            raise RuntimeError("cross_loop_store_access")
        return await super().get_run(run_id)


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


def test_recover_interrupted_runs_marks_inflight_runs_failed(tmp_path: Path) -> None:
    orch = _make_orchestrator(tmp_path)
    inflight = RunRecord(
        run_id="r-inflight",
        trace_id="t-inflight",
        status=RunStatus.SLIDES_GENERATING,
        input=CreateRunRequest(topic="Recover", project_id="p-recover"),
        artifact_dir=str(tmp_path / "artifacts" / "r-inflight"),
    )
    waiting = RunRecord(
        run_id="r-waiting",
        trace_id="t-waiting",
        status=RunStatus.AWAITING_OUTLINE_CONFIRM,
        input=CreateRunRequest(topic="Recover Waiting", project_id="p-recover"),
        artifact_dir=str(tmp_path / "artifacts" / "r-waiting"),
    )
    asyncio.run(orch.store.add_run(inflight))
    asyncio.run(orch.store.add_run(waiting))

    async def scenario() -> None:
        summary = await orch.recover_interrupted_runs()
        assert summary["scanned"] == 2
        assert summary["recovered"] == 1

        recovered = await orch.store.get_run("r-inflight")
        assert recovered is not None
        assert recovered.status == RunStatus.FAILED
        assert recovered.error_code == "RUN_INTERRUPTED_BY_RESTART"
        assert recovered.retryable is True

        untouched = await orch.store.get_run("r-waiting")
        assert untouched is not None
        assert untouched.status == RunStatus.AWAITING_OUTLINE_CONFIRM

    asyncio.run(scenario())


def test_kernel_create_run_should_execute_outline_in_same_event_loop(tmp_path: Path) -> None:
    orch = RunOrchestrator(
        store=_LoopBoundRunStore(base_dir=tmp_path),
        artifacts_base=tmp_path / "artifacts",
        templates_base=tmp_path / "templates",
        llm_client=MockLLMClient(),
        settings=make_settings(),
    )
    outline_stage = _NoopStage()
    kernel = RunKernel(
        orchestrator=orch,
        outline_stage=outline_stage,
        scratch_stage=_NoopStage(),
        template_stage=_NoopStage(),
    )

    async def scenario() -> None:
        summary = await kernel.create_run(CreateRunRequest(topic="Loop Safety", project_id="p-loop"))
        for _ in range(40):
            if summary.run_id in outline_stage.executed:
                break
            await asyncio.sleep(0.01)
        assert summary.run_id in outline_stage.executed

    asyncio.run(scenario())
