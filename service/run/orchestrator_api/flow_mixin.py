from __future__ import annotations


class RunFlowApiMixin:
    async def _generate_outline(self, run_id: str) -> None:
        await self._kernel.start_outline(run_id)

    async def _execute_generation_pipeline(self, run_id: str) -> None:
        await self._kernel.execute_generation_pipeline(run_id)

    async def _generate_from_scratch(self, run_id: str) -> None:
        await self._scratch_flow.execute(run_id)

    async def _finalize_run_success(
        self, run_id: str, *, from_stage: str, reason: str
    ) -> None:
        await self._kernel.finalize_run_success(
            run_id, from_stage=from_stage, reason=reason
        )

    async def _generate_from_template(self, run_id: str) -> None:
        await self._template_flow.execute(run_id)
