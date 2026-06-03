from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ...models.contracts_shared import RunEvent, RunStatus


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
    title: str = ""
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
    title: str = ""
    items: list[GeneratedItem] = Field(default_factory=list, min_length=1)
    source_refs: list[str] = Field(default_factory=list)
    revision_targets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LongFormStageTimings(BaseModel):
    plan_ms: int = 0
    draft_ms: int = 0
    revision_ms: int = 0


class LongFormPlanHistoryEntry(BaseModel):
    action: str
    approved: bool
    base_version: int | None = None
    new_version: int | None = None
    change_reason: str | None = None
    at: str


class LongFormRunDetailResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    content_kind: str = "longform_draft"
    plan: LongFormPlan | None
    plan_history: list[LongFormPlanHistoryEntry]
    draft: LongFormDraft | None
    structure_expansion: StructureExpansionResult | None = None
    item_generation: ItemGenerationResult | None = None
    stage_timings: LongFormStageTimings
    error_code: str | None
    failed_stage: str | None
    retryable: bool
    error_details: dict[str, object]
    research_report: dict[str, object]
    events: list[RunEvent]


class LongFormSectionRevisionResponse(BaseModel):
    run_id: str
    trace_id: str
    status: RunStatus
    draft_version: int = Field(ge=1)
    section: LongFormDraftSection
