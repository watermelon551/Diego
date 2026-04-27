from __future__ import annotations

from .longform_planning_runtime import (
    LLMLongFormPlanGenerationMixin,
    LLMLongFormPlanRevisionMixin,
    LLMLongFormRequirementsMixin,
)


class LLMLongFormPlanningMixin(
    LLMLongFormRequirementsMixin,
    LLMLongFormPlanGenerationMixin,
    LLMLongFormPlanRevisionMixin,
):
    """Thin longform planning facade layered over explicit planning mixins."""


__all__ = ["LLMLongFormPlanningMixin"]
