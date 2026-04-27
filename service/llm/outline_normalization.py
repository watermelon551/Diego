from __future__ import annotations

from ..models import SlidePageType
from ..design.skill_profile import allowed_layouts_for
from .normalization_runtime import (
    LLMLongFormNormalizationMixin,
    LLMOutlineDocumentNormalizationMixin,
)


class LLMOutlineNormalizationMixin(
    LLMOutlineDocumentNormalizationMixin,
    LLMLongFormNormalizationMixin,
):
    def _normalize_layout_hint(
        self,
        *,
        raw: str,
        page_type: SlidePageType,
        fallback: str | None,
    ) -> str | None:
        allowed = allowed_layouts_for(page_type)
        if raw in allowed:
            return raw
        if fallback and fallback in allowed:
            return fallback
        return allowed[0] if allowed else None


__all__ = ["LLMOutlineNormalizationMixin"]
