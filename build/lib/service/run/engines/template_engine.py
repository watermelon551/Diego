from __future__ import annotations

from pathlib import Path
from typing import Any

from ...design.skill_profile import DesignProfile
from ...models import SlideArtifact
from ..services.compile_service import CompileService


class TemplateEngine:
    def __init__(self, runtime: Any) -> None:
        self._service = CompileService(runtime)

    def template_work_paths(self, artifact_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
        return self._service.template_work_paths(artifact_dir)

    def pack_template_unpacked(self, *, unpacked: Path, edited: Path) -> None:
        self._service.pack_template_unpacked(unpacked=unpacked, edited=edited)

    async def compile_template_js(self, *, template_slides_dir: Path) -> bool:
        return await self._service.compile_template_js(template_slides_dir=template_slides_dir)

    async def apply_template_nodes_once(
        self,
        *,
        run_id: str,
        unpacked: Path,
        design: DesignProfile,
        use_review: bool,
        forced_issues: list[str] | None,
    ) -> list[SlideArtifact] | None:
        return await self._service.apply_template_nodes_once(
            run_id=run_id,
            unpacked=unpacked,
            design=design,
            use_review=use_review,
            forced_issues=forced_issues,
        )

    async def revise_template_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        return await self._service.revise_template_slides(
            run_id=run_id,
            design=design,
            forced_issues=forced_issues,
        )
