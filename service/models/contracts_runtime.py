from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .contracts_content import (
    ItemGenerationResult,
    ItemGenerationRunRequest,
    LongFormDraft,
    LongFormPlan,
    LongFormPlanHistoryEntry,
    LongFormRunDetailResponse,
    LongFormRunRequest,
    LongFormStageTimings,
    StructureExpansionResult,
    StructureExpansionRunRequest,
)
from .contracts_ppt import (
    CompileBundleResult,
    CompileResult,
    GenerationResult,
    OutlineHistoryEntry,
    SlideArtifact,
    StageTimings,
)
from .contracts_shared import (
    CreateRunRequest,
    OutlineDocument,
    RunEvent,
    RunStatus,
)


class RunRecord(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    input: (
        CreateRunRequest
        | LongFormRunRequest
        | StructureExpansionRunRequest
        | ItemGenerationRunRequest
    )
    outline: Optional[OutlineDocument] = None
    outline_history: list[OutlineHistoryEntry] = Field(default_factory=list)
    longform_plan: Optional[LongFormPlan] = None
    longform_plan_history: list[LongFormPlanHistoryEntry] = Field(default_factory=list)
    longform_draft: Optional[LongFormDraft] = None
    structure_expansion_result: Optional[StructureExpansionResult] = None
    item_generation_result: Optional[ItemGenerationResult] = None
    slides: list[SlideArtifact] = Field(default_factory=list)
    citation_map: dict[int, list[str]] = Field(default_factory=dict)
    events: list[RunEvent] = Field(default_factory=list)
    stage_timings: StageTimings = Field(default_factory=StageTimings)
    longform_stage_timings: LongFormStageTimings = Field(default_factory=LongFormStageTimings)
    render_version: int = 0
    error_code: Optional[str] = None
    failed_stage: Optional[str] = None
    retryable: bool = False
    error_details: dict[str, Any] = Field(default_factory=dict)
    artifact_dir: str
    compile_js_path: Optional[str] = None
    pptx_path: Optional[str] = None
    compile_requested_provider: Optional[str] = None
    compile_provider: Optional[str] = None
    compile_status: str = "not_requested"
    compile_bundle_ready: bool = False
    compile_fallback_used: bool = False
    compile_error_code: Optional[str] = None
    compile_error_details: dict[str, Any] = Field(default_factory=dict)
    qa_report: dict[str, Any] = Field(default_factory=dict)
    template_mapping_report: dict[str, Any] = Field(default_factory=dict)
    chart_truth_report: dict[str, Any] = Field(default_factory=dict)
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    quality_gate_report: dict[str, Any] = Field(default_factory=dict)
    research_report: dict[str, Any] = Field(default_factory=dict)
    candidate_selection_report: dict[str, Any] = Field(default_factory=dict)
    template_layout_report: dict[str, Any] = Field(default_factory=dict)
    artifact_cleanup_report: dict[str, Any] = Field(default_factory=dict)


class RunSummaryResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus


class RunDetailResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    pptx_ready: bool = False
    artifacts: dict[str, Any] = Field(default_factory=dict)
    outline: Optional[OutlineDocument]
    outline_history: list[OutlineHistoryEntry]
    slides: list[SlideArtifact]
    citation_map: dict[int, list[str]]
    stage_timings: StageTimings
    render_version: int = 0
    error_code: Optional[str]
    failed_stage: Optional[str]
    retryable: bool
    error_details: dict[str, Any]
    generation_result: GenerationResult
    compile_bundle: CompileBundleResult
    compile_result: CompileResult
    qa_report: dict[str, Any]
    template_mapping_report: dict[str, Any]
    chart_truth_report: dict[str, Any]
    repair_history: list[dict[str, Any]]
    quality_report: dict[str, Any]
    quality_gate_report: dict[str, Any]
    research_report: dict[str, Any]
    candidate_selection_report: dict[str, Any]
    template_layout_report: dict[str, Any]
    artifact_cleanup_report: dict[str, Any]
    events: list[RunEvent]
