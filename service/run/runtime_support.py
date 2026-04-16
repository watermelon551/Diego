from __future__ import annotations

from typing import Any

from .asset_flow_mixin import RunAssetFlowMixin
from ..slides.js_quality_mixin import SlideJsQualityMixin
from ..templates.template_ops_mixin import TemplateOpsMixin


class RuntimeSupport(RunAssetFlowMixin, SlideJsQualityMixin, TemplateOpsMixin):
    """Legacy capability surface hosted behind explicit composition."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)
