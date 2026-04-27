from __future__ import annotations

from typing import Any

from .draft_runtime_mixin import ContentDraftRuntimeMixin
from .plan_runtime_mixin import ContentPlanRuntimeMixin
from .retrieval_runtime_mixin import ContentRetrievalRuntimeMixin
from .run_lifecycle_mixin import ContentRunLifecycleMixin
from .structured_generation_mixin import StructuredContentGenerationMixin


class LongFormContentService(
    ContentRunLifecycleMixin,
    ContentPlanRuntimeMixin,
    ContentDraftRuntimeMixin,
    ContentRetrievalRuntimeMixin,
    StructuredContentGenerationMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator
