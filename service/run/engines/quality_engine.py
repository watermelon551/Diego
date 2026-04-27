from __future__ import annotations

from typing import Any

from ...design.skill_profile import DesignProfile
from ...models import GenerationMode, OutlineNode
from ..services.quality_repair import QualityRepairService


class QualityEngine:
    def __init__(self, runtime: Any) -> None:
        self._service = QualityRepairService(runtime)

    async def complete_post_compile_quality(
        self,
        *,
        run_id: str,
        mode: GenerationMode,
        design: DesignProfile,
    ) -> bool:
        return await self._service.complete_post_compile_quality(run_id=run_id, mode=mode, design=design)

    async def mandatory_polish_cycle(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        return await self._service.mandatory_polish_cycle(run_id, mode=mode, design=design)

    async def repair_loop(self, run_id: str, *, mode: GenerationMode, design: DesignProfile) -> bool:
        return await self._service.repair_loop(run_id, mode=mode, design=design)

    async def revise_scratch_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        return await self._service.revise_scratch_slides(run_id=run_id, design=design, forced_issues=forced_issues)

    def check_slide_content_rules(self, candidate: Any, node: OutlineNode) -> list[str]:
        return self._service.check_slide_content_rules(candidate, node)

    def extract_candidate_from_js(self, *args: Any, **kwargs: Any) -> Any:
        return self._service.extract_candidate_from_js(*args, **kwargs)
