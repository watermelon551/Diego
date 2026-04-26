from __future__ import annotations

from typing import Any

from ..content import LongFormContentService
from ..models import (
    ConfirmLongFormPlanRequest,
    LongFormRunDetailResponse,
    LongFormRunRequest,
    ItemGenerationRunRequest,
    LongFormSectionRevisionResponse,
    ReviseLongFormSectionRequest,
    StructureExpansionRunRequest,
    RunSummaryResponse,
)


class ContentApplicationService:
    def __init__(self, orchestrator: Any) -> None:
        self._service = LongFormContentService(orchestrator)

    async def create_run(
        self,
        req: LongFormRunRequest | StructureExpansionRunRequest | ItemGenerationRunRequest,
    ) -> RunSummaryResponse:
        return await self._service.create_run(req)

    async def get_run_detail(
        self, run_id: str
    ) -> LongFormRunDetailResponse | None:
        return await self._service.get_run_detail(run_id)

    async def confirm_plan(
        self, run_id: str, req: ConfirmLongFormPlanRequest
    ) -> RunSummaryResponse | None:
        return await self._service.confirm_plan(run_id, req)

    async def revise_section(
        self, run_id: str, section_id: str, req: ReviseLongFormSectionRequest
    ) -> LongFormSectionRevisionResponse | None:
        return await self._service.revise_section(run_id, section_id, req)
