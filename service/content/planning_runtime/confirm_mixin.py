from __future__ import annotations

from typing import Any

from ...infra.store import now_iso
from ...models import (
    ConfirmLongFormPlanRequest,
    EventType,
    LongFormPlanHistoryEntry,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
)


class ContentPlanConfirmMixin:
    orch: Any

    async def confirm_plan(
        self, run_id: str, req: ConfirmLongFormPlanRequest
    ) -> RunSummaryResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "") != "content":
            return None
        if str(getattr(run.input, "content_kind", "")) != "longform_draft":
            raise ValueError("plan confirmation is only available for longform_draft")
        if run.status != RunStatus.AWAITING_PLAN_CONFIRM:
            raise ValueError("run is not awaiting plan confirmation")
        if run.longform_plan is None:
            raise ValueError("run plan is missing")
        if req.plan is not None:
            if req.base_version != run.longform_plan.version:
                raise ValueError(
                    f"base_version mismatch: expected {run.longform_plan.version}, got {req.base_version}"
                )
            if req.plan.version <= run.longform_plan.version:
                req.plan.version = run.longform_plan.version + 1

        def apply_confirm(record: RunRecord) -> None:
            current_version = (
                record.longform_plan.version if record.longform_plan is not None else None
            )
            if req.plan is not None:
                record.longform_plan = req.plan
            record.status = (
                RunStatus.DRAFTING if req.approved else RunStatus.AWAITING_PLAN_CONFIRM
            )
            new_version = (
                record.longform_plan.version if record.longform_plan is not None else None
            )
            action = (
                "confirmed"
                if req.approved
                else ("updated" if req.plan is not None else "rejected")
            )
            record.longform_plan_history.append(
                LongFormPlanHistoryEntry(
                    action=action,
                    approved=req.approved,
                    base_version=current_version,
                    new_version=new_version,
                    change_reason=req.change_reason,
                    at=now_iso(),
                )
            )

        await self.orch.store.update_run(run_id, apply_confirm)
        if req.plan is not None:
            await self.orch._publish(
                run_id,
                EventType.PLAN_UPDATED,
                {
                    "approved": req.approved,
                    "base_version": req.base_version,
                    "new_version": req.plan.version,
                    "change_reason": req.change_reason,
                },
            )
        if req.approved:
            self.orch._spawn(self.generate_draft(run_id))
        updated = await self.orch.store.get_run(run_id)
        assert updated is not None
        return RunSummaryResponse(
            run_id=updated.run_id, trace_id=updated.trace_id, status=updated.status
        )
