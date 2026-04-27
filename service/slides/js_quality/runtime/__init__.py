from __future__ import annotations

from .diagnostics_runtime_mixin import SlideJsDiagnosticsRuntimeMixin
from .normalization_runtime_mixin import SlideJsNormalizationRuntimeMixin
from .validation_runtime_mixin import SlideJsValidationRuntimeMixin


class SlideJsQualityMixin(
    SlideJsNormalizationRuntimeMixin,
    SlideJsDiagnosticsRuntimeMixin,
    SlideJsValidationRuntimeMixin,
):
    pass


__all__ = ["SlideJsQualityMixin"]
