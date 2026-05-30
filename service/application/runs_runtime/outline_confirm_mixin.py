from __future__ import annotations

from ...design.skill_profile import enforce_layout_variety
from ...infra.store import now_iso
from ...models import (
    ConfirmOutlineRequest,
    EventType,
    OutlineHistoryEntry,
    RunRecord,
    RunStatus,
    RunSummaryResponse,
)


class RunApplicationOutlineConfirmMixin:
    async def confirm_outline(
        self, run_id: str, req: ConfirmOutlineRequest
    ) -> RunSummaryResponse | None:
        run = await self.orch.store.get_run(run_id)
        if run is None or getattr(run.input, "capability", "ppt") != "ppt":
            return None
        if run.status != RunStatus.AWAITING_OUTLINE_CONFIRM:
            raise ValueError("run is not awaiting outline confirmation")
        if run.outline is None:
            raise ValueError("run outline is missing")
        if req.outline is not None:
            if req.base_version != run.outline.version:
                raise ValueError(
                    f"base_version mismatch: expected {run.outline.version}, got {req.base_version}"
                )
            enforce_layout_variety(
                nodes=req.outline.nodes,
                seed=f"{run.input.topic}|{self.orch._resolved_template_style(run)}|{run_id}|confirm",
                style_dna_id=self.orch._resolved_style_dna_id(run),
            )
            if req.outline.version <= run.outline.version:
                req.outline.version = run.outline.version + 1

        def apply_confirm(record: RunRecord) -> None:
            current_version = record.outline.version if record.outline is not None else None
            if req.outline is not None:
                record.outline = req.outline
            record.status = (
                RunStatus.SLIDES_GENERATING
                if req.approved
                else RunStatus.AWAITING_OUTLINE_CONFIRM
            )
            new_version = record.outline.version if record.outline is not None else None
            action = (
                "confirmed"
                if req.approved
                else ("updated" if req.outline is not None else "rejected")
            )
            record.outline_history.append(
                OutlineHistoryEntry(
                    action=action,
                    approved=req.approved,
                    base_version=current_version,
                    new_version=new_version,
                    change_reason=req.change_reason,
                    at=now_iso(),
                )
            )

        await self.orch.store.update_run(run_id, apply_confirm)
        if req.outline is not None:
            await self.orch._publish(
                run_id,
                EventType.OUTLINE_UPDATED,
                {
                    "approved": req.approved,
                    "base_version": req.base_version,
                    "new_version": req.outline.version,
                    "change_reason": req.change_reason,
                },
            )
        if req.approved:
            self.orch._spawn(self.orch._kernel.execute_generation_pipeline(run_id), run_id=run_id)
        updated = await self.orch.store.get_run(run_id)
        assert updated is not None
        return RunSummaryResponse(
            run_id=updated.run_id,
            trace_id=updated.trace_id,
            status=updated.status,
        )
