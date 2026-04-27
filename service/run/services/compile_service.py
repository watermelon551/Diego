from __future__ import annotations

from pathlib import Path
from typing import Any

from .compile_template_candidate_extraction_mixin import (
    CompileTemplateCandidateExtractionMixin,
)
from .compile_template_apply_mixin import CompileTemplateApplyMixin
from .compile_template_runtime_mixin import CompileTemplateRuntimeMixin


class CompileService(
    CompileTemplateRuntimeMixin,
    CompileTemplateApplyMixin,
    CompileTemplateCandidateExtractionMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator
