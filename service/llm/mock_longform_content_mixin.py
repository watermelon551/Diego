from __future__ import annotations

from .mock_longform_runtime import (
    MockLongFormDraftingMixin,
    MockLongFormPlanningMixin,
    MockStructuredContentGenerationMixin,
)


class MockLongFormContentMixin(
    MockLongFormPlanningMixin,
    MockLongFormDraftingMixin,
    MockStructuredContentGenerationMixin,
):
    """Thin mock longform facade layered over explicit mock capability mixins."""


__all__ = ["MockLongFormContentMixin"]
