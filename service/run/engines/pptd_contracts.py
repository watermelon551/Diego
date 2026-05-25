from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PptdSlideContent:
    index: int
    total: int
    title: str
    bullets: list[str]
    page_type: str = "content"
    layout_hint: str = ""
    source_note: str = ""

    @property
    def page_no(self) -> int:
        return self.index + 1
