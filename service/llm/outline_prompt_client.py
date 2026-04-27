from __future__ import annotations

from .outline_runtime import LLMOutlinePlanningMixin, LLMOutlineRequirementsMixin


class LLMOutlinePromptMixin(
    LLMOutlineRequirementsMixin,
    LLMOutlinePlanningMixin,
):
    """Thin outline prompt facade layered over explicit requirements/planning mixins."""


__all__ = ["LLMOutlinePromptMixin"]
