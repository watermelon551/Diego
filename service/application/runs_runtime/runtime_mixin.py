from __future__ import annotations

from typing import Any

from ...models import RunRecord, RunStatus, RunSummaryResponse


class RunApplicationRuntimeMixin:
    async def create_run(self, req: Any) -> RunSummaryResponse:
        return await self.orch._kernel.create_run(req)

    async def build_compile_bundle(self, run_id: str) -> dict[str, Any]:
        return await self.orch.compile_engine.build_compile_bundle(run_id)

    async def get_run_record(self, run_id: str) -> RunRecord | None:
        return await self.orch.store.get_run(run_id)

    async def wait_for_event(
        self, run_id: str, cursor: int, timeout: float = 5.0
    ) -> RunRecord:
        return await self.orch.store.wait_for_event(run_id, cursor, timeout=timeout)

    async def recover_interrupted_runs(self) -> dict[str, int]:
        interrupted_statuses = {
            RunStatus.PLANNING,
            RunStatus.DRAFTING,
            RunStatus.OUTLINE_DRAFTING,
            RunStatus.SLIDES_GENERATING,
            RunStatus.COMPILING,
        }
        runs = await self.orch.store.list_runs()
        recovered = 0
        for run in runs:
            if run.status not in interrupted_statuses:
                continue
            recovered += 1
            await self.orch._kernel.fail_run(
                run.run_id,
                run.status.value,
                "RUN_INTERRUPTED_BY_RESTART",
                retryable=True,
                error_details={
                    "reason": "service_restarted",
                    "previous_status": run.status.value,
                },
            )
        return {"scanned": len(runs), "recovered": recovered}
