from __future__ import annotations

from typing import Any

from .drafting_runtime import (
    ContentDraftGenerationMixin,
    ContentDraftRevisionMixin,
    ContentDraftShapeMixin,
)


class ContentDraftRuntimeMixin(
    ContentDraftRevisionMixin,
    ContentDraftGenerationMixin,
    ContentDraftShapeMixin,
):
    orch: Any
