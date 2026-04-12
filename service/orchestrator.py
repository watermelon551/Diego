from __future__ import annotations

from ._compat import maybe_warn_legacy_import
from .run import orchestrator as _run_orchestrator
from .run.orchestrator import RunOrchestrator, build_orchestrator
from .run.types import (
    SlideGenerationError,
    TemplateAssetError,
    TemplateLayoutConflictError,
    TemplateSlotMappingError,
    VisualPolicyUnsatisfiedError,
)

maybe_warn_legacy_import(legacy="service.orchestrator", replacement="service.run.orchestrator")

# Legacy monkeypatch compatibility: tests patch service.orchestrator.subprocess.run.
subprocess = _run_orchestrator.subprocess

__all__ = [
    "RunOrchestrator",
    "build_orchestrator",
    "SlideGenerationError",
    "TemplateAssetError",
    "TemplateLayoutConflictError",
    "TemplateSlotMappingError",
    "VisualPolicyUnsatisfiedError",
    "subprocess",
]
