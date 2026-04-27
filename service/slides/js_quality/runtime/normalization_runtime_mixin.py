from __future__ import annotations

from ....models import OutlineNode
from ..canonicalization import auto_canonicalize_slide_js
from ..normalization import normalize_generated_slide_js


class SlideJsNormalizationRuntimeMixin:
    def _normalize_generated_slide_js(
        self,
        js_code: str,
        *,
        slide_no: int,
        node: OutlineNode,
        target_slide_count: int,
    ) -> tuple[str, list[str]]:
        return normalize_generated_slide_js(
            js_code,
            slide_no=slide_no,
            node=node,
            target_slide_count=target_slide_count,
            dedupe_preserve_order=self._dedupe_preserve_order,
        )

    def _auto_canonicalize_slide_js(
        self,
        js_code: str,
        *,
        slide_no: int,
        node: OutlineNode,
        target_slide_count: int,
    ) -> tuple[str, list[str]]:
        return auto_canonicalize_slide_js(
            js_code,
            slide_no=slide_no,
            node=node,
            target_slide_count=target_slide_count,
            legal_shape_enum=list(self._js_api_contract.get("legal_shape_enum", []) or []),
            split_top_level_args=self._split_top_level_args,
            find_matching_delimiter=lambda payload, start_idx, open_char, close_char: self._find_matching_delimiter(
                payload,
                start_idx=start_idx,
                open_char=open_char,
                close_char=close_char,
            ),
            dedupe_preserve_order=self._dedupe_preserve_order,
        )
