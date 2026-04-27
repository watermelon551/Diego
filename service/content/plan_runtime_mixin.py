from __future__ import annotations

from typing import Any

from .plan_confirm_mixin import ContentPlanConfirmMixin
from .plan_generation_mixin import ContentPlanGenerationMixin
from .plan_requirements_mixin import ContentPlanRequirementsMixin


class ContentPlanRuntimeMixin(
    ContentPlanConfirmMixin,
    ContentPlanRequirementsMixin,
    ContentPlanGenerationMixin,
):
    orch: Any
