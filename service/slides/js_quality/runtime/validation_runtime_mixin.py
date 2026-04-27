from __future__ import annotations

from ....models import SlidePageType, VisualPolicy
from ..call_parsing import extract_method_call_args
from ..contract_validation import validate_slide_js_contract
from ..guardrails import apply_local_js_guardrails, has_valid_page_badge
from ..issue_resolution import (
    build_local_repair_directives,
    classify_slide_issues,
    fallback_quality_gate,
    issues_have_fatal_markers,
    local_quality_score,
)
from ..layout_analysis import collect_js_style_issues
from ..parsing_runtime import find_matching_delimiter, split_top_level_args


class SlideJsValidationRuntimeMixin:
    def _validate_slide_js_contract(
        self,
        js_code: str,
        *,
        slide_no: int,
        page_type: str,
        visual_policy: VisualPolicy = VisualPolicy.AUTO,
        slide_plan: dict[str, object] | None = None,
    ) -> list[str]:
        return validate_slide_js_contract(
            js_code,
            slide_no=slide_no,
            page_type=page_type,
            visual_policy=visual_policy,
            slide_plan=slide_plan,
            extract_method_call_args=lambda payload, method_expr: self._extract_method_call_args(
                payload,
                method_expr=method_expr,
            ),
            dedupe_preserve_order=self._dedupe_preserve_order,
            collect_js_style_issues=lambda **kwargs: self._collect_js_style_issues(
                **kwargs
            ),
        )

    def _extract_method_call_args(
        self, js_code: str, *, method_expr: str
    ) -> list[list[str]]:
        return extract_method_call_args(
            js_code,
            method_expr=method_expr,
            split_top_level_args=self._split_top_level_args,
        )

    def _apply_local_js_guardrails(
        self,
        *,
        js_code: str,
        slide_no: int,
        page_type: SlidePageType,
    ) -> str:
        return apply_local_js_guardrails(
            js_code=js_code,
            slide_no=slide_no,
            page_type=page_type,
            has_valid_page_badge=lambda **kwargs: has_valid_page_badge(**kwargs),
        )

    def _has_valid_page_badge(self, *, js_code: str, slide_no: int) -> bool:
        return has_valid_page_badge(js_code=js_code, slide_no=slide_no)

    def _classify_slide_issues(self, issues: list[str]) -> dict[str, list[str]]:
        return classify_slide_issues(
            issues,
            dedupe_preserve_order=self._dedupe_preserve_order,
        )

    def _local_quality_score(self, *, classified: dict[str, list[str]]) -> int:
        return local_quality_score(classified=classified)

    def _build_local_repair_directives(
        self, *, classified: dict[str, list[str]]
    ) -> list[str]:
        return build_local_repair_directives(
            classified=classified,
            dedupe_preserve_order=self._dedupe_preserve_order,
        )

    def _issues_have_fatal_markers(self, issues: list[str]) -> bool:
        return issues_have_fatal_markers(issues)

    def _collect_js_style_issues(self, *, js_code: str, page_type: str) -> list[str]:
        return collect_js_style_issues(
            js_code=js_code,
            page_type=page_type,
            find_matching_delimiter=lambda payload, start_idx, open_char, close_char: self._find_matching_delimiter(
                payload,
                start_idx=start_idx,
                open_char=open_char,
                close_char=close_char,
            ),
            split_top_level_args=self._split_top_level_args,
            dedupe_preserve_order=self._dedupe_preserve_order,
        )

    def _find_matching_delimiter(
        self, text: str, *, start_idx: int, open_char: str, close_char: str
    ) -> int:
        return find_matching_delimiter(
            text,
            start_idx=start_idx,
            open_char=open_char,
            close_char=close_char,
        )

    def _split_top_level_args(self, raw_args: str) -> list[str]:
        return split_top_level_args(raw_args)

    def _fallback_quality_gate(
        self, *, hard_issues: list[str], preview_text: str, candidate_js: str
    ) -> dict[str, object]:
        return fallback_quality_gate(
            hard_issues=hard_issues,
            preview_text=preview_text,
            candidate_js=candidate_js,
        )
