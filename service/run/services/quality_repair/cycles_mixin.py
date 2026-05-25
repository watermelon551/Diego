from __future__ import annotations

from typing import Any

from ....design.skill_profile import DesignProfile
from ....models import EventType, GenerationMode, RunRecord, RunStatus
from ...repair_mode_execution import execute_repair_round_mode
from ...repair_round_reporting import (
    build_repair_history_entry,
    build_repair_round_completed_payload,
    build_repair_started_payload,
    increment_verification_cycles,
)


class QualityRepairCyclesMixin:
    orch: Any

    async def complete_post_compile_quality(
        self,
        *,
        run_id: str,
        mode: GenerationMode,
        design: DesignProfile,
    ) -> bool:
        orch = self.orch
        if not orch.settings.qa_enabled:
            return True
        latest = await orch.store.get_run(run_id)
        if latest is not None and str(
            getattr(latest, "compile_requested_provider", "")
            or getattr(latest, "compile_provider", "")
            or ""
        ).lower() == "pptd":
            def apply_pptd_qa(record: RunRecord) -> None:
                previous = (
                    record.qa_report
                    if isinstance(getattr(record, "qa_report", None), dict)
                    else {}
                )
                record.qa_report = {
                    **previous,
                    "passed": True,
                    "degraded": True,
                    "degraded_reason": "PPTD_RUNTIME_CHECKED",
                    "mode": mode.value,
                }

            await orch.store.update_run(run_id, apply_pptd_qa)
            await orch._publish(
                run_id,
                EventType.QA_COMPLETED,
                {
                    "passed": True,
                    "degraded": True,
                    "degraded_reason": "PPTD_RUNTIME_CHECKED",
                    "mode": mode.value,
                },
            )
            await orch._publish(
                run_id,
                EventType.SLIDE_PREVIEW_QA,
                {
                    "mode": mode.value,
                    "status": "skipped",
                    "reason": "pptd_runtime_checked",
                },
            )
            return True
        polish_ok = await self.mandatory_polish_cycle(run_id, mode=mode, design=design)
        if not polish_ok:
            latest = await orch.store.get_run(run_id)
            if latest is not None and latest.status == RunStatus.FAILED:
                return False
            qa_details = await orch._persist_qa_failure_artifacts(run_id=run_id, mode=mode)
            await orch._fail_run(
                run_id,
                "COMPILING",
                "QA_FAILED",
                retryable=False,
                error_details=qa_details,
            )
            return False
        latest_after_polish = await orch.store.get_run(run_id)
        qa_ok = bool(
            latest_after_polish
            and isinstance(latest_after_polish.qa_report, dict)
            and latest_after_polish.qa_report.get("passed", False)
        )
        if not qa_ok:
            qa_ok = await self.repair_loop(run_id, mode=mode, design=design)
        if qa_ok:
            return True
        latest = await orch.store.get_run(run_id)
        if latest is not None and latest.status == RunStatus.FAILED:
            return False
        qa_details = await orch._persist_qa_failure_artifacts(run_id=run_id, mode=mode)
        await orch._fail_run(
            run_id, "COMPILING", "QA_FAILED", retryable=False, error_details=qa_details
        )
        return False

    async def mandatory_polish_cycle(
        self, run_id: str, *, mode: GenerationMode, design: DesignProfile
    ) -> bool:
        orch = self.orch
        await orch._publish(
            run_id,
            EventType.REPAIR_STARTED,
            build_repair_started_payload(
                repair_round=0,
                mode=mode.value,
                reason="mandatory_verify_cycle",
            ),
        )
        run = await orch.store.get_run(run_id)
        if run is None:
            return False
        execution = await execute_repair_round_mode(
            orchestrator=orch,
            run_id=run_id,
            mode=mode,
            design=design,
            forced_issues=["mandatory polish cycle"],
            revise_scratch_slides=self.revise_scratch_slides,
        )
        if execution.terminal_failure or not execution.advanced:
            return False
        qa_ok = await orch._run_skill_qa(run_id, mode=mode)

        def apply_cycle(r: RunRecord) -> None:
            increment_verification_cycles(r.qa_report)

        await orch.store.update_run(run_id, apply_cycle)
        await orch._append_repair_history(
            run_id=run_id,
            entry=build_repair_history_entry(
                repair_round=0,
                mode=mode.value,
                qa_passed=qa_ok,
            ),
        )
        await orch._publish(
            run_id,
            EventType.REPAIR_ROUND_COMPLETED,
            build_repair_round_completed_payload(
                repair_round=0,
                mode=mode.value,
                qa_passed=qa_ok,
            ),
        )
        return True

    async def repair_loop(
        self, run_id: str, *, mode: GenerationMode, design: DesignProfile
    ) -> bool:
        orch = self.orch
        for repair_round in range(1, orch.repair_rounds + 1):
            await orch._publish(
                run_id,
                EventType.REPAIR_STARTED,
                build_repair_started_payload(
                    repair_round=repair_round,
                    mode=mode.value,
                ),
            )
            execution = await execute_repair_round_mode(
                orchestrator=orch,
                run_id=run_id,
                mode=mode,
                design=design,
                forced_issues=None,
                revise_scratch_slides=self.revise_scratch_slides,
            )
            if execution.terminal_failure:
                return False
            if not execution.advanced:
                continue
            qa_ok = await orch._run_skill_qa(run_id, mode=mode)
            await orch._append_repair_history(
                run_id=run_id,
                entry=build_repair_history_entry(
                    repair_round=repair_round,
                    mode=mode.value,
                    qa_passed=qa_ok,
                ),
            )
            await orch._publish(
                run_id,
                EventType.REPAIR_ROUND_COMPLETED,
                build_repair_round_completed_payload(
                    repair_round=repair_round,
                    mode=mode.value,
                    qa_passed=qa_ok,
                ),
            )
            if qa_ok:
                return True
        return False
