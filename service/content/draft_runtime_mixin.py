from __future__ import annotations

from typing import Any

from .draft_generation_mixin import ContentDraftGenerationMixin
from .draft_revision_mixin import ContentDraftRevisionMixin
from .draft_shape_mixin import ContentDraftShapeMixin


class ContentDraftRuntimeMixin(
    ContentDraftRevisionMixin,
    ContentDraftGenerationMixin,
    ContentDraftShapeMixin,
):
    orch: Any
