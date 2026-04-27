from __future__ import annotations

from dataclasses import dataclass, field

from ..models import SlidePageType


@dataclass
class GeneratedSlide:
    title: str
    bullets: list[str]
    citations: list[str]
    page_type: SlidePageType
    layout_hint: str | None = None


@dataclass
class SlideSpec:
    title: str
    bullets: list[str]
    page_type: SlidePageType
    layout_hint: str | None = None
    visual_kind: str = "shape"
    subtitle: str = ""
    emphasis: str = ""
    citations: list[str] = field(default_factory=list)
