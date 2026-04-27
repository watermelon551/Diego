from __future__ import annotations

from .orchestrator_api import (
    RunApplicationApiMixin,
    RunFlowApiMixin,
    RunQualityTemplateApiMixin,
    RunSlideSceneApiMixin,
)


class RunOrchestratorApiMixin(
    RunApplicationApiMixin,
    RunSlideSceneApiMixin,
    RunFlowApiMixin,
    RunQualityTemplateApiMixin,
):
    """Thin run-owned API facade layered over explicit capability mixins."""


__all__ = ["RunOrchestratorApiMixin"]
