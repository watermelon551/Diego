from __future__ import annotations

from pathlib import Path

from ...design.skill_profile import DesignProfile
from ...models import GenerationMode
from ..preview_quality import run_skill_qa
from ..template_artifact_cleanup import cleanup_orphan_media


class RunQualityTemplateApiMixin:
    async def _complete_post_compile_quality(
        self,
        *,
        run_id: str,
        mode: GenerationMode,
        design: DesignProfile,
    ) -> bool:
        return await self.quality_engine.complete_post_compile_quality(
            run_id=run_id, mode=mode, design=design
        )

    def _template_work_paths(
        self, artifact_dir: Path
    ) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
        return self.template_engine.template_work_paths(artifact_dir)

    def _pack_template_unpacked(self, *, unpacked: Path, edited: Path) -> None:
        self.template_engine.pack_template_unpacked(unpacked=unpacked, edited=edited)

    async def _compile_template_js(self, *, template_slides_dir: Path) -> bool:
        return await self.template_engine.compile_template_js(
            template_slides_dir=template_slides_dir
        )

    async def _apply_template_nodes_once(
        self,
        *,
        run_id: str,
        unpacked: Path,
        design: DesignProfile,
        use_review: bool,
        forced_issues: list[str] | None,
    ):
        return await self.template_engine.apply_template_nodes_once(
            run_id=run_id,
            unpacked=unpacked,
            design=design,
            use_review=use_review,
            forced_issues=forced_issues,
        )

    async def _revise_template_slides(
        self, *, run_id: str, design: DesignProfile, forced_issues: list[str] | None
    ) -> bool:
        return await self.template_engine.revise_template_slides(
            run_id=run_id,
            design=design,
            forced_issues=forced_issues,
        )

    def _cleanup_orphan_media(self, *, unpacked: Path) -> None:
        cleanup_orphan_media(unpacked=unpacked, parse_xml_attrs=self._parse_xml_attrs)

    async def _run_skill_qa(self, run_id: str, *, mode: GenerationMode) -> bool:
        return await run_skill_qa(self, run_id, mode=mode)

    async def _mandatory_polish_cycle(
        self, run_id: str, *, mode: GenerationMode, design: DesignProfile
    ) -> bool:
        return await self.quality_engine.mandatory_polish_cycle(
            run_id, mode=mode, design=design
        )

    async def _repair_loop(
        self, run_id: str, *, mode: GenerationMode, design: DesignProfile
    ) -> bool:
        return await self.quality_engine.repair_loop(run_id, mode=mode, design=design)

    async def _compile_scratch_slides(self, run_id: str) -> bool:
        run = await self.store.get_run(run_id)
        if run is None:
            return False
        result = await self.compile_engine.compile_scratch_run(
            run_id=run_id,
            slides_dir=Path(run.artifact_dir) / "slides",
            slide_count=len(run.slides),
            theme=self._resolve_design_profile(
                topic=run.input.topic,
                template_style=self._resolved_template_style(run),
                requirements_report=(
                    run.research_report if isinstance(run.research_report, dict) else {}
                ),
            ).theme,
        )
        return bool(result["ok"])

    async def _revise_scratch_slides(
        self,
        *,
        run_id: str,
        design: DesignProfile,
        forced_issues: list[str] | None,
    ) -> bool:
        return await self.quality_engine.revise_scratch_slides(
            run_id=run_id,
            design=design,
            forced_issues=forced_issues,
        )
