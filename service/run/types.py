from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

class TemplateAssetError(RuntimeError):
    pass


class VisualPolicyUnsatisfiedError(RuntimeError):
    pass


class TemplateLayoutConflictError(RuntimeError):
    def __init__(self, *, slide_no: int, issues: list[str]) -> None:
        super().__init__(f"template layout conflict on slide {slide_no}")
        self.slide_no = slide_no
        self.issues = issues


class TemplateSlotMappingError(RuntimeError):
    def __init__(self, *, slide_no: int, missing_slots: list[dict[str, Any]]) -> None:
        super().__init__(f"template slot mapping failed on slide {slide_no}")
        self.slide_no = slide_no
        self.missing_slots = missing_slots


class SlideGenerationError(RuntimeError):
    def __init__(
        self,
        *,
        slide_no: int,
        phase: str,
        reason: str,
        round_no: int | None = None,
        candidate: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.slide_no = slide_no
        self.phase = phase
        self.reason = reason.strip() if reason else "slide generation failed"
        self.round_no = round_no
        self.candidate = candidate
        self.details = dict(details or {})
        message = f"slide {slide_no} {phase}: {self.reason}"
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "slide_no": self.slide_no,
            "phase": self.phase,
            "reason": self.reason,
        }
        if self.round_no is not None:
            payload["round"] = self.round_no
        if self.candidate is not None:
            payload["candidate"] = self.candidate
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class SlotNode:
    slot_id: str
    slot_type: str
    required: bool
    rel_id: str | None = None
    hint: str = ""
    group_id: str | None = None


@dataclass
class SlotGraph:
    slide_no: int
    slots: list[SlotNode] = field(default_factory=list)


@dataclass
class ChartFact:
    label: str
    value: float
    unit: str
    source_ref: str


@dataclass
class ChartPlan:
    has_verified_data: bool
    mode: str
    labels: list[str]
    values: list[float]
    unit: str
    note: str
    source: str


@dataclass
class LayoutBox:
    element_type: str
    xml_tag: str
    block_start: int
    block_end: int
    x_emu: int
    y_emu: int
    w_emu: int
    h_emu: int
    rel_id: str | None = None
    element_id: str | None = None

    @property
    def x(self) -> float:
        return self.x_emu / 914400.0

    @property
    def y(self) -> float:
        return self.y_emu / 914400.0

    @property
    def w(self) -> float:
        return self.w_emu / 914400.0

    @property
    def h(self) -> float:
        return self.h_emu / 914400.0


@dataclass
class JsLayoutBox:
    element_type: str
    x: float
    y: float
    w: float
    h: float
    text_expr: str = ""
    options_raw: str = ""
    font_size: float | None = None
    align: str | None = None
    bold: bool | None = None
    fit: str | None = None

    @property
    def area(self) -> float:
        return self.w * self.h


SLIDE_WIDTH_EMU = 9_144_000
SLIDE_HEIGHT_EMU = 5_143_500
SLIDE_WIDTH_IN = 10.0
SLIDE_HEIGHT_IN = 5.625

