from __future__ import annotations

from pathlib import Path

from ..design.skill_profile import DesignProfile
from ..models import OutlineNode, SlideArtifact
from .agentic_slide_generation import generate_agentic_slide
from .legacy_slide_generation import generate_legacy_skill_slide
from .slide_generation_plan_adapter_mixin import SlideGenerationPlanAdapterMixin
from .slide_generation_render_adapter_mixin import SlideGenerationRenderAdapterMixin


class RunSlideGenerationPrimitivesMixin(
    SlideGenerationPlanAdapterMixin,
    SlideGenerationRenderAdapterMixin,
):
    def _build_slide_plan(self, **kwargs): return SlideGenerationPlanAdapterMixin._build_slide_plan(self, **kwargs)
    def _apply_local_spec_repairs(self, **kwargs): return SlideGenerationPlanAdapterMixin._apply_local_spec_repairs(self, **kwargs)
    def _rotate_layout_hint(self, **kwargs): return SlideGenerationPlanAdapterMixin._rotate_layout_hint(self, **kwargs)
    def _trim_spec_bullets(self, **kwargs): return SlideGenerationPlanAdapterMixin._trim_spec_bullets(self, **kwargs)
    def _build_slide_brief(self, **kwargs): return SlideGenerationPlanAdapterMixin._build_slide_brief(self, **kwargs)
    def _candidate_variant_specs(self, **kwargs): return SlideGenerationPlanAdapterMixin._candidate_variant_specs(self, **kwargs)
    def _fallback_research_brief(self, **kwargs): return SlideGenerationPlanAdapterMixin._fallback_research_brief(self, **kwargs)
    def _slide_spec_from_generated(self, **kwargs): return SlideGenerationPlanAdapterMixin._slide_spec_from_generated(self, **kwargs)
    def _generated_from_slide_spec(self, **kwargs): return SlideGenerationPlanAdapterMixin._generated_from_slide_spec(self, **kwargs)
    def _render_skill_slide_js(self, **kwargs): return SlideGenerationRenderAdapterMixin._render_skill_slide_js(self, **kwargs)
    def _build_compile_script(self, **kwargs): return SlideGenerationRenderAdapterMixin._build_compile_script(self, **kwargs)
    def _slide_content_block(self, **kwargs): return SlideGenerationRenderAdapterMixin._slide_content_block(self, **kwargs)
    def _slide_block_cover(self, *args, **kwargs): return SlideGenerationRenderAdapterMixin._slide_block_cover(self, *args, **kwargs)
    def _slide_block_toc(self, *args, **kwargs): return SlideGenerationRenderAdapterMixin._slide_block_toc(self, *args, **kwargs)
    def _slide_block_section(self, *args, **kwargs): return SlideGenerationRenderAdapterMixin._slide_block_section(self, *args, **kwargs)
    def _slide_block_content(self, *args, **kwargs): return SlideGenerationRenderAdapterMixin._slide_block_content(self, *args, **kwargs)
    def _slide_block_summary(self, *args, **kwargs): return SlideGenerationRenderAdapterMixin._slide_block_summary(self, *args, **kwargs)

    async def _generate_skill_slide(
        self, *, run_id: str, slide_no: int, node: OutlineNode, design: DesignProfile
    ) -> SlideArtifact:
        run = await self.store.get_run(run_id)
        assert run is not None
        slides_dir = Path(run.artifact_dir) / "slides"
        if self._use_agentic_engine():
            return await generate_agentic_slide(
                self,
                run_id=run_id,
                slide_no=slide_no,
                node=node,
                design=design,
                slides_dir=slides_dir,
            )
        return await generate_legacy_skill_slide(
            self,
            run_id=run_id,
            slide_no=slide_no,
            node=node,
            design=design,
        )

    async def _generate_agentic_slide(
        self,
        *,
        run_id: str,
        slide_no: int,
        node: OutlineNode,
        design: DesignProfile,
        slides_dir: Path,
    ) -> SlideArtifact:
        return await generate_agentic_slide(
            self,
            run_id=run_id,
            slide_no=slide_no,
            node=node,
            design=design,
            slides_dir=slides_dir,
        )
