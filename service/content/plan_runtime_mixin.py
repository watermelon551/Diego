from __future__ import annotations

from typing import Any

from .planning_runtime import (
    ContentPlanConfirmMixin,
    ContentPlanGenerationMixin,
    ContentPlanRequirementsMixin,
)


class ContentPlanRuntimeMixin(
    ContentPlanConfirmMixin,
    ContentPlanRequirementsMixin,
    ContentPlanGenerationMixin,
):
    orch: Any
