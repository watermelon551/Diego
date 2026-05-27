from __future__ import annotations

from .slide_regeneration_scratch import (
    SlideRegenerationAgenticScratchMixin,
    SlideRegenerationScratchFinalizeMixin,
    SlideRegenerationScratchRuntimeMixin,
)


class SlideRegenerationScratchMixin(
    SlideRegenerationScratchRuntimeMixin,
    SlideRegenerationAgenticScratchMixin,
    SlideRegenerationScratchFinalizeMixin,
):
    """Thin scratch-regeneration facade that delegates into feature-local mixins."""


__all__ = ["SlideRegenerationScratchMixin"]
