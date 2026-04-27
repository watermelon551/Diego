from __future__ import annotations

from ..models import OutlineNode
from .parsing import _extract_json_object, _normalize_page_type
from .types import GeneratedSlide, SlideSpec


class LLMSlideResponseParsingMixin:
    def _parse_generated_slide(
        self, *, text: str, fallback: OutlineNode
    ) -> GeneratedSlide:
        payload = _extract_json_object(text)
        title = str(payload.get("title", "")).strip() or fallback.title
        bullets_raw = payload.get("bullets", [])
        if not isinstance(bullets_raw, list):
            bullets_raw = []
        bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
        if not bullets:
            bullets = fallback.bullets or [f"{title} point 1", f"{title} point 2"]

        citations_raw = payload.get("citations", [])
        if not isinstance(citations_raw, list):
            citations_raw = []
        citations = [str(item).strip() for item in citations_raw if str(item).strip()]
        page_type = _normalize_page_type(str(payload.get("page_type", "")))
        layout_hint = self._normalize_layout_hint(
            raw=str(payload.get("layout_hint", "")).strip(),
            page_type=page_type,
            fallback=fallback.layout_hint,
        )
        return GeneratedSlide(
            title=title,
            bullets=bullets,
            citations=citations,
            page_type=page_type,
            layout_hint=layout_hint,
        )

    def _parse_slide_spec(self, *, text: str, fallback: OutlineNode) -> SlideSpec:
        payload = _extract_json_object(text)
        title = str(payload.get("title", "")).strip() or fallback.title
        subtitle = str(payload.get("subtitle", "")).strip()
        emphasis = str(payload.get("emphasis", "")).strip()
        bullets_raw = payload.get("bullets", [])
        if not isinstance(bullets_raw, list):
            bullets_raw = []
        bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
        if not bullets:
            bullets = (
                list(fallback.bullets)
                if fallback.bullets
                else [f"{title} point 1", f"{title} point 2"]
            )
        citations_raw = payload.get("citations", [])
        if not isinstance(citations_raw, list):
            citations_raw = []
        citations = [str(item).strip() for item in citations_raw if str(item).strip()]
        page_type = _normalize_page_type(str(payload.get("page_type", ""))) or fallback.page_type
        layout_hint = self._normalize_layout_hint(
            raw=str(payload.get("layout_hint", "")).strip(),
            page_type=page_type,
            fallback=fallback.layout_hint,
        )
        visual_kind = str(payload.get("visual_kind", "")).strip().lower()
        if visual_kind not in {"image", "chart", "shape"}:
            visual_kind = "shape"
        return SlideSpec(
            title=title,
            subtitle=subtitle,
            bullets=bullets,
            page_type=page_type,
            layout_hint=layout_hint,
            visual_kind=visual_kind,
            emphasis=emphasis,
            citations=citations,
        )
