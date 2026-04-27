from __future__ import annotations

from typing import Any

from .cycles_mixin import QualityRepairCyclesMixin
from .scratch_revision_mixin import QualityScratchRevisionMixin
from .slide_candidate_parsing_mixin import QualitySlideCandidateParsingMixin


class QualityRepairService(
    QualityRepairCyclesMixin,
    QualityScratchRevisionMixin,
    QualitySlideCandidateParsingMixin,
):
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator
