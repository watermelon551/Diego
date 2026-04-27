from __future__ import annotations

from service.llm import GeneratedSlide
from service.models import EventType, OutlineNode, SlidePageType
from service.run.slide_candidate_execution import execute_agentic_candidate_build
from service.run.types import ChartPlan


async def _noop_publish(
    _run_id: str, _event_type: EventType, _payload: dict
) -> None:
    return None


def _node() -> OutlineNode:
    return OutlineNode(
        title="Hello",
        bullets=["One", "Two"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-two-column",
    )


def test_execute_agentic_candidate_build_should_use_build_path_when_no_best_js() -> None:
    events: list[tuple[str, dict]] = []

    async def publish(run_id: str, event_type: EventType, payload: dict) -> None:
        events.append((f"{run_id}:{event_type.value}", payload))

    async def call_build() -> str:
        return "raw-js"

    async def call_repair() -> str:
        raise AssertionError("repair path should not run")

    def extract_candidate(raw_js: str, raw_node: OutlineNode, raw_citations: list[str]) -> GeneratedSlide:
        assert raw_js == "guarded-js"
        return GeneratedSlide(
            title=raw_node.title,
            bullets=list(raw_node.bullets),
            citations=list(raw_citations),
            page_type=raw_node.page_type,
            layout_hint=raw_node.layout_hint,
        )

    def build_chart_plan(raw_node: OutlineNode, raw_citations: list[str]) -> ChartPlan:
        assert raw_node.title == "Hello"
        assert raw_citations == ["s1", "s2"]
        return ChartPlan(
            has_verified_data=False,
            mode="qualitative_fallback",
            labels=[],
            values=[],
            unit="",
            note="No verified data",
            source="",
        )

    import asyncio

    result = asyncio.run(
        execute_agentic_candidate_build(
            run_id="run-1",
            slide_no=1,
            repair_round=1,
            target_slide_count=4,
            node=_node(),
            rag_source_ids=["s1", "s2"],
            best_js="",
            auto_canonicalize_enabled=False,
            call_build=call_build,
            call_repair=call_repair,
            normalize_citations=lambda _cits, _rag_ids, _slide_no: ["s1", "s2"],
            normalize_generated_js=lambda raw_js, *_args: (raw_js, []),
            auto_canonicalize_js=lambda raw_js, *_args: (raw_js, []),
            dedupe_preserve_order=lambda items: items,
            publish=publish,
            apply_local_js_guardrails=lambda raw_js, *_args: raw_js.replace("raw", "guarded"),
            extract_candidate_from_js=extract_candidate,
            build_chart_plan_from_bullets=build_chart_plan,
        )
    )
    assert result.llm_phase == "candidate.build"
    assert result.js_code == "guarded-js"
    assert result.citations == ["s1", "s2"]
    assert result.generated.title == "Hello"
    assert result.chart_plan.mode == "qualitative_fallback"
    assert events == []


def test_execute_agentic_candidate_build_should_use_repair_path_and_publish_auto_fixes() -> None:
    events: list[tuple[str, dict]] = []

    async def publish(run_id: str, event_type: EventType, payload: dict) -> None:
        events.append((f"{run_id}:{event_type.value}", payload))

    async def call_build() -> str:
        raise AssertionError("build path should not run")

    async def call_repair() -> str:
        return "repair-js"

    import asyncio

    result = asyncio.run(
        execute_agentic_candidate_build(
            run_id="run-2",
            slide_no=2,
            repair_round=2,
            target_slide_count=5,
            node=_node(),
            rag_source_ids=["s1"],
            best_js="existing-best-js",
            auto_canonicalize_enabled=True,
            call_build=call_build,
            call_repair=call_repair,
            normalize_citations=lambda _cits, _rag_ids, _slide_no: ["s1"],
            normalize_generated_js=lambda raw_js, *_args: (raw_js + "-normalized", ["fix-a"]),
            auto_canonicalize_js=lambda raw_js, *_args: (raw_js + "-canon", ["fix-b"]),
            dedupe_preserve_order=lambda items: list(dict.fromkeys(items)),
            publish=publish,
            apply_local_js_guardrails=lambda raw_js, *_args: raw_js + "-guarded",
            extract_candidate_from_js=lambda _raw_js, raw_node, raw_citations: GeneratedSlide(
                title=raw_node.title,
                bullets=list(raw_node.bullets),
                citations=list(raw_citations),
                page_type=raw_node.page_type,
                layout_hint=raw_node.layout_hint,
            ),
            build_chart_plan_from_bullets=lambda _raw_node, _raw_citations: ChartPlan(
                has_verified_data=False,
                mode="qualitative_fallback",
                labels=[],
                values=[],
                unit="",
                note="No verified data",
                source="",
            ),
        )
    )
    assert result.llm_phase == "candidate.repair"
    assert result.js_code == "repair-js-normalized-canon-guarded"
    assert len(events) == 1
    event_name, payload = events[0]
    assert event_name == "run-2:slide.auto.fix.applied"
    assert payload["fixes"] == ["fix-a", "fix-b"]
