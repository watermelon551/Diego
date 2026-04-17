from __future__ import annotations

from pathlib import Path
from typing import Any

from .asset_flow_mixin import RunAssetFlowMixin
from ..slides.js_quality_mixin import SlideJsQualityMixin
from ..templates.template_ops_mixin import TemplateOpsMixin


class RuntimeSupport(RunAssetFlowMixin, SlideJsQualityMixin, TemplateOpsMixin):
    """Legacy capability surface hosted behind explicit composition."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def __getattribute__(self, name: str) -> Any:
        if name in {
            "_owner",
            "__class__",
            "__dict__",
            "__getattribute__",
            "__getattr__",
        }:
            return object.__getattribute__(self, name)
        owner = object.__getattribute__(self, "_owner")
        owner_dict = object.__getattribute__(owner, "__dict__")
        if name in owner_dict:
            return owner_dict[name]
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            return object.__getattribute__(owner, name)


class LegacyCompileServiceAdapter:
    def __init__(self, owner: Any) -> None:
        self._owner = owner

    async def compile_template_js(self, *, template_slides_dir: Any) -> bool:
        return await self._owner.template_engine.compile_template_js(template_slides_dir=template_slides_dir)

    async def compile_scratch_slides(self, *, run_id: str) -> bool:
        run = await self._owner.store.get_run(run_id)
        if run is None:
            return False
        result = await self._owner.compile_engine.compile_scratch_run(
            run_id=run_id,
            slides_dir=Path(run.artifact_dir) / "slides",
            slide_count=len(run.slides),
            theme=self._owner._resolve_design_profile(
                topic=run.input.topic,
                template_style=self._owner._resolved_template_style(run),
                requirements_report=run.research_report if isinstance(run.research_report, dict) else {},
            ).theme,
        )
        return bool(result.get("ok"))
