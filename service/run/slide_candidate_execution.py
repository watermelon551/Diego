from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from ..llm import GeneratedSlide
from ..models import EventType, OutlineNode
from .types import ChartPlan


@dataclass
class CandidateExecutionResult:
    llm_phase: str
    js_code: str
    citations: list[str]
    generated: GeneratedSlide
    chart_plan: ChartPlan


async def execute_agentic_candidate_build(
    *,
    run_id: str,
    slide_no: int,
    repair_round: int,
    target_slide_count: int,
    node: OutlineNode,
    rag_source_ids: list[str],
    best_js: str,
    auto_canonicalize_enabled: bool,
    call_build: Callable[[], Awaitable[str]],
    call_repair: Callable[[], Awaitable[str]],
    normalize_citations: Callable[[list[str], list[str], int], list[str]],
    normalize_generated_js: Callable[[str, int, OutlineNode, int], tuple[str, list[str]]],
    auto_canonicalize_js: Callable[[str, int, OutlineNode, int], tuple[str, list[str]]],
    dedupe_preserve_order: Callable[[list[str]], list[str]],
    publish: Callable[[str, EventType, dict], Awaitable[None]],
    apply_local_js_guardrails: Callable[[str, int, object], str],
    extract_candidate_from_js: Callable[[str, OutlineNode, list[str]], GeneratedSlide],
    build_chart_plan_from_bullets: Callable[[OutlineNode, list[str]], ChartPlan],
) -> CandidateExecutionResult:
    llm_phase = "candidate.build"
    citations = normalize_citations([], rag_source_ids, slide_no)

    if repair_round == 1 or not best_js:
        js_code = await call_build()
    else:
        llm_phase = "candidate.repair"
        js_code = await call_repair()

    js_code, normalize_fixes = normalize_generated_js(
        js_code,
        slide_no,
        node,
        target_slide_count,
    )
    auto_fixes: list[str] = []
    if auto_canonicalize_enabled:
        js_code, auto_fixes = auto_canonicalize_js(
            js_code,
            slide_no,
            node,
            target_slide_count,
        )
    if normalize_fixes or auto_fixes:
        await publish(
            run_id,
            EventType.SLIDE_AUTO_FIX_APPLIED,
            {
                "slide_no": slide_no,
                "round": repair_round,
                "candidate": 1,
                "fixes": dedupe_preserve_order(normalize_fixes + auto_fixes)[:24],
            },
        )

    js_code = apply_local_js_guardrails(js_code, slide_no, node.page_type)
    generated = extract_candidate_from_js(js_code, node, citations)
    chart_plan = build_chart_plan_from_bullets(
        OutlineNode(
            title=generated.title,
            bullets=list(generated.bullets),
            page_type=node.page_type,
            layout_hint=generated.layout_hint or node.layout_hint,
        ),
        citations,
    )
    return CandidateExecutionResult(
        llm_phase=llm_phase,
        js_code=js_code,
        citations=citations,
        generated=generated,
        chart_plan=chart_plan,
    )
