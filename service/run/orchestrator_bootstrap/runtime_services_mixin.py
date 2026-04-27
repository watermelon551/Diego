from __future__ import annotations

from ..background_runtime_mixin import RunBackgroundRuntimeMixin
from ..design_resolution_mixin import RunDesignResolutionMixin
from ..engines import (
    AssetResolver,
    CompileEngine,
    QualityEngine,
    ReportingEngine,
    ScratchSlideEngine,
    TemplateEngine,
)
from ..flows import OutlineFlowService, ScratchFlowService, TemplateFlowService
from ..kernel import RunKernel
from ..llm_runtime_mixin import RunLlmRuntimeMixin
from ..outline_rag_runtime_mixin import RunOutlineRagRuntimeMixin
from ..preview_quality import RunPreviewRuntimeMixin
from ..reporting_runtime_mixin import RunReportingRuntimeMixin
from ..runtime_support import LegacyCompileServiceAdapter, RuntimeSupport
from ..services import SlideRegenerationService
from ..slide_generation_primitives_mixin import RunSlideGenerationPrimitivesMixin
from ..stages import (
    FinalizeQualityStage,
    OutlineStage,
    ScratchGenerationStage,
    TemplateGenerationStage,
)


class RunRuntimeServicesMixin(
    RunBackgroundRuntimeMixin,
    RunDesignResolutionMixin,
    RunLlmRuntimeMixin,
    RunOutlineRagRuntimeMixin,
    RunPreviewRuntimeMixin,
    RunReportingRuntimeMixin,
    RunSlideGenerationPrimitivesMixin,
):
    def _initialize_runtime_services(self) -> None:
        self._support = RuntimeSupport(self)
        self.asset_resolver = AssetResolver(self._support)
        self.scratch_engine = ScratchSlideEngine(self._support)
        self.template_engine = TemplateEngine(self._support)
        self.compile_engine = CompileEngine(self._support)
        self.quality_engine = QualityEngine(self._support)
        self.reporting_engine = ReportingEngine(self._support)
        self.slide_regeneration_service = SlideRegenerationService(self)
        self._legacy_aliases = {
            "_compile_service": LegacyCompileServiceAdapter(self),
            "_quality_service": self.quality_engine,
            "_reporting_service": self.reporting_engine,
        }
        self._outline_flow = OutlineFlowService(self)
        self._scratch_flow = ScratchFlowService(self)
        self._template_flow = TemplateFlowService(self)
        self.finalize_quality_stage = FinalizeQualityStage(self)
        self._kernel = RunKernel(
            orchestrator=self,
            outline_stage=OutlineStage(self._outline_flow),
            scratch_stage=ScratchGenerationStage(self._scratch_flow),
            template_stage=TemplateGenerationStage(self._template_flow),
        )
        from ...application.facade import DiegoApplication

        self.application = DiegoApplication(self)
