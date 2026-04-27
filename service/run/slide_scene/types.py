from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import EditableSlideScene


@dataclass(frozen=True)
class _Binding:
    kind: str
    value_span: tuple[int, int]
    value: str
    label: str
    source_order: int
    bbox: dict[str, float] | None
    style: dict[str, Any]
    edit_capabilities: list[str]


@dataclass(frozen=True)
class _ParsedScene:
    scene: EditableSlideScene
    bindings: dict[str, _Binding]
