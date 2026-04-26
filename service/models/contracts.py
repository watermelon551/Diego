from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from ..design.style_catalog import (
    STYLE_PRESET_AUTO,
    is_valid_style_choice,
    normalize_style_choice,
)


class RunStatus(str, Enum):
    PLANNING = "PLANNING"
    AWAITING_PLAN_CONFIRM = "AWAITING_PLAN_CONFIRM"
    DRAFTING = "DRAFTING"
    OUTLINE_DRAFTING = "OUTLINE_DRAFTING"
    AWAITING_OUTLINE_CONFIRM = "AWAITING_OUTLINE_CONFIRM"
    SLIDES_GENERATING = "SLIDES_GENERATING"
    COMPILING = "COMPILING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EventType(str, Enum):
    REQUIREMENTS_ANALYZING_STARTED = "requirements.analyzing.started"
    REQUIREMENTS_ANALYZING_COMPLETED = "requirements.analyzing.completed"
    REQUIREMENTS_ANALYZED = "requirements.analyzed"
    RAG_RETRIEVAL_STARTED = "rag.retrieval.started"
    RAG_RETRIEVAL_COMPLETED = "rag.retrieval.completed"
    RAG_RETRIEVAL_FAILED = "rag.retrieval.failed"
    OUTLINE_TOKEN = "outline.token"
    OUTLINE_COMPLETED = "outline.completed"
    OUTLINE_UPDATED = "outline.updated"
    PLAN_TOKEN = "plan.token"
    PLAN_UPDATED = "plan.updated"
    SECTION_GENERATED = "section.generated"
    SECTION_REVISED = "section.revised"
    STRUCTURE_EXPANSION_COMPLETED = "structure.expansion.completed"
    ITEM_GENERATION_COMPLETED = "item.generation.completed"
    SLIDE_GENERATED = "slide.generated"
    COMPILE_COMPLETED = "compile.completed"
    RUN_FAILED = "run.failed"
    SLIDE_STARTED = "slide.started"
    COMPILE_STARTED = "compile.started"
    PLAN_COMPLETED = "plan.completed"
    SLIDE_REVIEWED = "slide.reviewed"
    QA_COMPLETED = "qa.completed"
    REPAIR_STARTED = "repair.started"
    SLOT_MAPPING_COMPLETED = "slot.mapping.completed"
    SLIDE_PREVIEW_QA = "slide.preview.qa"
    CHART_TRUTH_CHECKED = "chart.truth.checked"
    REPAIR_ROUND_COMPLETED = "repair.round.completed"
    SLIDE_CODEGEN_STARTED = "slide.codegen.started"
    SLIDE_CODEGEN_COMPLETED = "slide.codegen.completed"
    SLIDE_SPEC_GENERATED = "slide.spec.generated"
    SLIDE_SPEC_REPAIRED = "slide.spec.repaired"
    SLIDE_CRITIC_COMPLETED = "slide.critic.completed"
    SLIDE_REPAIR_COMPLETED = "slide.repair.completed"
    ARTIFACT_CLEANUP_COMPLETED = "artifact.cleanup.completed"
    SLIDE_PLAN_COMPLETED = "slide.plan.completed"
    SLIDE_QUALITY_GATE_COMPLETED = "slide.quality.gate.completed"
    SLIDE_REPAIR_DIRECTIVES_GENERATED = "slide.repair.directives.generated"
    RESEARCH_COMPLETED = "research.completed"
    SLIDE_CANDIDATE_GENERATED = "slide.candidate.generated"
    SLIDE_SELECTION_COMPLETED = "slide.selection.completed"
    TEMPLATE_LAYOUT_REFLOW_COMPLETED = "template.layout.reflow.completed"
    TEMPLATE_FIDELITY_CHECKED = "template.fidelity.checked"
    OUTLINE_REPAIR_STARTED = "outline.repair.started"
    OUTLINE_REPAIR_COMPLETED = "outline.repair.completed"
    OUTLINE_REPAIR_FAILED = "outline.repair.failed"
    LLM_REQUEST_RETRY = "llm.request.retry"
    LLM_REQUEST_TIMEOUT = "llm.request.timeout"
    SLIDE_FAILED = "slide.failed"
    SLIDE_FAILURE_DIAGNOSTICS = "slide.failure.diagnostics"
    SLIDE_AUTO_FIX_APPLIED = "slide.auto.fix.applied"
    SLIDE_RETRY_CONTEXT_BUILT = "slide.retry.context.built"
    RUN_FINALIZED = "run.finalized"


class GenerationMode(str, Enum):
    SCRATCH = "scratch"
    TEMPLATE = "template"


class VisualPolicy(str, Enum):
    AUTO = "auto"
    MEDIA_REQUIRED = "media_required"
    BASIC_GRAPHICS_ONLY = "basic_graphics_only"


class SlidePageType(str, Enum):
    COVER = "cover"
    TOC = "toc"
    SECTION = "section"
    CONTENT = "content"
    SUMMARY = "summary"


class CreateRunRequest(BaseModel):
    capability: Literal["ppt"] = "ppt"
    topic: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    template_style: str = Field(default="default")
    style_preset: str = Field(default=STYLE_PRESET_AUTO)
    target_slide_count: int = Field(default=8, ge=1, le=50)
    generation_mode: GenerationMode = GenerationMode.SCRATCH
    template_id: Optional[str] = None
    visual_policy: VisualPolicy = VisualPolicy.AUTO

    @model_validator(mode="after")
    def validate_mode(self) -> "CreateRunRequest":
        self.style_preset = normalize_style_choice(self.style_preset)
        if not is_valid_style_choice(self.style_preset):
            raise ValueError(f"invalid style_preset={self.style_preset!r}")
        if self.generation_mode == GenerationMode.TEMPLATE and not self.template_id:
            raise ValueError("template_id is required when generation_mode=template")
        return self


class PromptRunRequest(BaseModel):
    capability: Literal["ppt"] = "ppt"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    template_style: str = Field(default="default")
    style_preset: str = Field(default=STYLE_PRESET_AUTO)
    target_slide_count: int = Field(default=8, ge=1, le=50)
    generation_mode: GenerationMode = GenerationMode.SCRATCH
    template_id: Optional[str] = None
    visual_policy: VisualPolicy = VisualPolicy.AUTO

    @model_validator(mode="after")
    def validate_mode(self) -> "PromptRunRequest":
        self.style_preset = normalize_style_choice(self.style_preset)
        if not is_valid_style_choice(self.style_preset):
            raise ValueError(f"invalid style_preset={self.style_preset!r}")
        if self.generation_mode == GenerationMode.TEMPLATE and not self.template_id:
            raise ValueError("template_id is required when generation_mode=template")
        return self

    def to_create_run_request(self) -> CreateRunRequest:
        return CreateRunRequest(
            topic=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            template_style=self.template_style,
            style_preset=self.style_preset,
            target_slide_count=self.target_slide_count,
            generation_mode=self.generation_mode,
            template_id=self.template_id,
            visual_policy=self.visual_policy,
        )


class OutlineNode(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    page_type: SlidePageType = SlidePageType.CONTENT
    layout_hint: Optional[str] = None


class OutlineDocument(BaseModel):
    version: int
    nodes: list[OutlineNode]
    summary: str


class LongFormRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["longform_draft"] = "longform_draft"
    topic: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    audience: str = Field(default="general audience")
    purpose: str = Field(default="explain the topic clearly")
    tone: str = Field(default="professional")
    target_section_count: int = Field(default=5, ge=1, le=24)


class LongFormPromptRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["longform_draft"] = "longform_draft"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    audience: str = Field(default="general audience")
    purpose: str = Field(default="explain the topic clearly")
    tone: str = Field(default="professional")
    target_section_count: int = Field(default=5, ge=1, le=24)

    def to_create_run_request(self) -> "LongFormRunRequest":
        return LongFormRunRequest(
            content_kind=self.content_kind,
            topic=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            audience=self.audience,
            purpose=self.purpose,
            tone=self.tone,
            target_section_count=self.target_section_count,
        )


class ContentSourceScope(BaseModel):
    mode: Literal["project_all", "selected_sources"] = "project_all"
    selected_source_ids: list[str] = Field(default_factory=list)
    scope_note: str = ""


class StructureExpansionAnchorContext(BaseModel):
    anchor_label: str = ""
    anchor_summary: str = ""
    related_labels: list[str] = Field(default_factory=list)


class StructureExpansionRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["structure_expansion"] = "structure_expansion"
    generation_goal: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    anchor_context: StructureExpansionAnchorContext = Field(
        default_factory=StructureExpansionAnchorContext
    )
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="units")


class StructureExpansionPromptRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["structure_expansion"] = "structure_expansion"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    anchor_context: StructureExpansionAnchorContext = Field(
        default_factory=StructureExpansionAnchorContext
    )
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="units")

    def to_create_run_request(self) -> "StructureExpansionRunRequest":
        return StructureExpansionRunRequest(
            generation_goal=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            source_scope=self.source_scope,
            evidence_refs=self.evidence_refs,
            anchor_context=self.anchor_context,
            constraints=self.constraints,
            requested_output_shape=self.requested_output_shape,
        )


class ItemGenerationRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["item_generation"] = "item_generation"
    generation_goal: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="items")


class ItemGenerationPromptRunRequest(BaseModel):
    capability: Literal["content"] = "content"
    content_kind: Literal["item_generation"] = "item_generation"
    prompt: str = Field(min_length=1)
    project_id: str = Field(default="default-project", min_length=1)
    rag_source_ids: list[str] = Field(default_factory=list)
    source_scope: ContentSourceScope = Field(default_factory=ContentSourceScope)
    evidence_refs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    requested_output_shape: str = Field(default="items")

    def to_create_run_request(self) -> "ItemGenerationRunRequest":
        return ItemGenerationRunRequest(
            generation_goal=self.prompt,
            project_id=self.project_id,
            rag_source_ids=self.rag_source_ids,
            source_scope=self.source_scope,
            evidence_refs=self.evidence_refs,
            constraints=self.constraints,
            requested_output_shape=self.requested_output_shape,
        )


class LongFormPlanSection(BaseModel):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    intent: str = ""
    source_refs: list[str] = Field(default_factory=list)


class LongFormPlan(BaseModel):
    version: int = Field(ge=1)
    title: str = Field(min_length=1)
    summary: str = ""
    sections: list[LongFormPlanSection] = Field(default_factory=list, min_length=1)


class ContentBlock(BaseModel):
    kind: Literal["heading", "paragraph", "bullet_list", "quote"]
    text: str = ""
    items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_payload(self) -> "ContentBlock":
        if self.kind == "bullet_list":
            if not self.items:
                raise ValueError("bullet_list block requires items")
            self.text = ""
        else:
            if not str(self.text or "").strip():
                raise ValueError(f"{self.kind} block requires text")
            self.items = []
        return self


class LongFormDraftSection(BaseModel):
    section_id: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    blocks: list[ContentBlock] = Field(default_factory=list, min_length=1)
    citations: list[str] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)


class LongFormDraftStats(BaseModel):
    section_count: int = 0
    block_count: int = 0
    citation_count: int = 0


class LongFormDraft(BaseModel):
    content_schema: Literal["content_blocks_v1"] = "content_blocks_v1"
    version: int = Field(default=1, ge=1)
    title: str = Field(min_length=1)
    summary: str = ""
    sections: list[LongFormDraftSection] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    stats: LongFormDraftStats = Field(default_factory=LongFormDraftStats)


class StructureExpansionUnit(BaseModel):
    unit_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    anchor_ref: str = ""
    revision_target: str = ""


class StructureExpansionResult(BaseModel):
    schema_version: Literal["structure_expansion_v1"] = "structure_expansion_v1"
    content_kind: Literal["structure_expansion"] = "structure_expansion"
    units: list[StructureExpansionUnit] = Field(default_factory=list, min_length=1)
    anchors: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    revision_targets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GeneratedItem(BaseModel):
    item_id: str = Field(min_length=1)
    stem: str = Field(min_length=1)
    choices: list[str] = Field(default_factory=list)
    expected_response: str = ""
    expected_response_hints: list[str] = Field(default_factory=list)
    explanation: str = ""
    source_refs: list[str] = Field(default_factory=list)
    difficulty: str = ""
    intent: str = ""


class ItemGenerationResult(BaseModel):
    schema_version: Literal["item_generation_v1"] = "item_generation_v1"
    content_kind: Literal["item_generation"] = "item_generation"
    items: list[GeneratedItem] = Field(default_factory=list, min_length=1)
    source_refs: list[str] = Field(default_factory=list)
    revision_targets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SlideArtifact(BaseModel):
    slide_no: int
    js_path: Optional[str] = None
    js_code: str
    status: str
    citations: list[str] = Field(default_factory=list)


class GenerationResult(BaseModel):
    mode: GenerationMode
    artifact_dir: Optional[str] = None
    outline_ready: bool = False
    slide_count: int = 0
    slide_artifacts_ready: bool = False
    citation_map_ready: bool = False
    compile_bundle_ready: bool = False
    compile_bundle_entrypoint: Optional[str] = None


class CompileBundleResult(BaseModel):
    status: str = "not_available"
    provider: str = "diego"
    available: bool = False
    entrypoint: Optional[str] = None
    build_endpoint: Optional[str] = None
    mode: Optional[str] = None


class CompileResult(BaseModel):
    status: str = "not_requested"
    requested_provider: Optional[str] = None
    provider: Optional[str] = None
    bundle_ready: bool = False
    artifact_path: Optional[str] = None
    artifact_ready: bool = False
    fallback_used: bool = False
    fallback_from: Optional[str] = None
    error_code: Optional[str] = None
    error_details: dict[str, Any] = Field(default_factory=dict)


class StageTimings(BaseModel):
    outline_ms: int = 0
    slide_ms: int = 0
    compile_ms: int = 0


class LongFormStageTimings(BaseModel):
    plan_ms: int = 0
    draft_ms: int = 0
    revision_ms: int = 0


class RunEvent(BaseModel):
    seq: int
    event: EventType
    ts: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ConfirmOutlineRequest(BaseModel):
    approved: bool = True
    outline: Optional[OutlineDocument] = None
    base_version: Optional[int] = None
    change_reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ConfirmOutlineRequest":
        if self.outline is not None and self.base_version is None:
            raise ValueError("base_version is required when outline is provided")
        if self.outline is None and self.change_reason:
            raise ValueError("change_reason requires outline")
        return self


class LongFormPlanHistoryEntry(BaseModel):
    action: str
    approved: bool
    base_version: Optional[int] = None
    new_version: Optional[int] = None
    change_reason: Optional[str] = None
    at: str


class ConfirmLongFormPlanRequest(BaseModel):
    approved: bool = True
    plan: Optional[LongFormPlan] = None
    base_version: Optional[int] = None
    change_reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ConfirmLongFormPlanRequest":
        if self.plan is not None and self.base_version is None:
            raise ValueError("base_version is required when plan is provided")
        if self.plan is None and self.change_reason:
            raise ValueError("change_reason requires plan")
        return self


class ReviseLongFormSectionRequest(BaseModel):
    instruction: str = Field(min_length=1)
    base_revision: int = Field(ge=1)
    preserve_structure: bool = True


class RegenerateSlideRequest(BaseModel):
    instruction: str = Field(min_length=1)
    preserve_style: bool = True
    expected_render_version: Optional[int] = Field(default=None, ge=1)


class EditableSlideNodeBBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class EditableSlideNode(BaseModel):
    node_id: str = Field(min_length=1)
    kind: Literal["text", "image"]
    label: str = Field(min_length=1)
    text: Optional[str] = None
    src: Optional[str] = None
    alt: Optional[str] = None
    bbox: Optional[EditableSlideNodeBBox] = None
    style: dict[str, Any] = Field(default_factory=dict)
    edit_capabilities: list[str] = Field(default_factory=list)


class EditableSlideScene(BaseModel):
    run_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    slide_index: int = Field(ge=0)
    slide_no: int = Field(ge=1)
    scene_version: str = Field(min_length=1)
    nodes: list[EditableSlideNode] = Field(default_factory=list)
    readonly: bool = False
    readonly_reason: Optional[str] = None


class SaveSlideSceneOperation(BaseModel):
    op: Literal["replace_text", "replace_image"]
    node_id: str = Field(min_length=1)
    value: str


class SaveSlideSceneRequest(BaseModel):
    scene_version: str = Field(min_length=1)
    operations: list[SaveSlideSceneOperation] = Field(
        default_factory=list, min_length=1
    )


class SaveSlideSceneResponse(BaseModel):
    run_id: str = Field(min_length=1)
    slide_id: str = Field(min_length=1)
    slide_index: int = Field(ge=0)
    slide_no: int = Field(ge=1)
    render_version: int = Field(default=0, ge=0)
    status: str = Field(default="ready")
    scene: EditableSlideScene
    preview: dict[str, Any] = Field(default_factory=dict)


class OutlineHistoryEntry(BaseModel):
    action: str
    approved: bool
    base_version: Optional[int] = None
    new_version: Optional[int] = None
    change_reason: Optional[str] = None
    at: str


class RunRecord(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    input: CreateRunRequest | LongFormRunRequest | StructureExpansionRunRequest | ItemGenerationRunRequest
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


class LongFormRunDetailResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    content_kind: str = "longform_draft"
    plan: Optional[LongFormPlan]
    plan_history: list[LongFormPlanHistoryEntry]
    draft: Optional[LongFormDraft]
    structure_expansion: Optional[StructureExpansionResult] = None
    item_generation: Optional[ItemGenerationResult] = None
    stage_timings: LongFormStageTimings
    error_code: Optional[str]
    failed_stage: Optional[str]
    retryable: bool
    error_details: dict[str, Any]
    research_report: dict[str, Any]
    events: list[RunEvent]


class LongFormSectionRevisionResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    draft_version: int = Field(ge=1)
    section: LongFormDraftSection


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
    compile_js_path: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Legacy mirror for compatibility. Prefer generation_result/compile_bundle/compile_result.",
    )
    pptx_path: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Legacy mirror for compatibility. Prefer artifacts.pptx for Diego-owned files and compile_result for explicit provider outcomes.",
    )
    compile_requested_provider: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Legacy mirror for compatibility. Prefer compile_result.requested_provider.",
    )
    compile_provider: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Legacy mirror for compatibility. Prefer compile_result.provider.",
    )
    compile_fallback_used: bool = Field(
        default=False,
        deprecated=True,
        description="Legacy mirror for compatibility. Prefer compile_result.fallback_used.",
    )
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


class TemplateRecord(BaseModel):
    template_id: str
    filename: str
    path: str
    created_at: str


class TemplateUploadResponse(BaseModel):
    template_id: str
    filename: str


class TemplateDetailResponse(BaseModel):
    template_id: str
    filename: str
    path: str
    created_at: str
