from __future__ import annotations

from .agentic_iteration_mixin import AgenticScratchRevisionIterationMixin
from .agentic_js_finalize_mixin import AgenticScratchRevisionJsFinalizeMixin
from .agentic_request_mixin import AgenticScratchRevisionRequestMixin
from .agentic_slide_plan_mixin import AgenticScratchRevisionSlidePlanMixin


class AgenticScratchRevisionMixin(
    AgenticScratchRevisionIterationMixin,
    AgenticScratchRevisionRequestMixin,
    AgenticScratchRevisionSlidePlanMixin,
    AgenticScratchRevisionJsFinalizeMixin,
):
    """Thin scratch-revision facade that keeps agentic repair steps feature-local."""


__all__ = ["AgenticScratchRevisionMixin"]
