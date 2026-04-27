from __future__ import annotations

from service.design.skill_profile import DesignProfile, STYLE_RECIPES
from service.models import OutlineNode, SlidePageType, VisualPolicy
from service.run.slide_generation_briefs import candidate_variant_specs, fallback_research_brief
from service.run.slide_plan_rules import apply_visual_policy_to_slide_plan, build_slide_plan
from service.run.slide_spec_repair import apply_local_spec_repairs
from service.llm import SlideSpec


def _design() -> DesignProfile:
    return DesignProfile(
        palette_name="Test",
        theme={
            "primary": "111111",
            "secondary": "222222",
            "accent": "333333",
            "light": "EEEEEE",
            "bg": "FFFFFF",
        },
        title_font="Arial",
        body_font="Arial",
        style=STYLE_RECIPES["soft"],
    )


def test_build_slide_plan_should_emit_content_visual_plan() -> None:
    node = OutlineNode(
        title="Topic",
        bullets=["a", "b"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-showcase",
    )
    plan = build_slide_plan(node=node, design=_design(), slide_no=2)
    assert plan["slide_no"] == 2
    assert plan["layout"] == "content-showcase"
    assert plan["visual_plan"]["kind"] == "image_or_showcase"
    assert plan["visual_plan"]["image_slots"] == 2


def test_apply_visual_policy_to_slide_plan_should_force_media_layouts() -> None:
    node = OutlineNode(
        title="Topic",
        bullets=["a", "b"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-timeline",
    )
    plan = build_slide_plan(node=node, design=_design(), slide_no=1)
    apply_visual_policy_to_slide_plan(
        slide_plan=plan,
        page_type=SlidePageType.CONTENT,
        visual_policy=VisualPolicy.MEDIA_REQUIRED,
    )
    assert plan["visual_plan"]["kind"] == "image_or_showcase"
    assert plan["visual_plan"]["image_slots"] >= 1
    assert plan["layout"] in {
        "content-two-column",
        "content-showcase",
        "content-icon-rows",
    }


def test_apply_local_spec_repairs_should_trim_and_repair_visual_kind() -> None:
    node = OutlineNode(
        title="Topic",
        bullets=["one", "two", "three", "four", "five"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-timeline",
    )
    spec = SlideSpec(
        title="Topic",
        subtitle="",
        bullets=["x" * 120, "y", "z", "w", "v"],
        page_type=SlidePageType.CONTENT,
        layout_hint="content-timeline",
        visual_kind="shape",
        emphasis="",
        citations=[],
    )
    repaired = apply_local_spec_repairs(
        spec=spec,
        node=node,
        repair_round=1,
        issues=[
            "visual_policy violation",
            "out of slide bounds",
            "fit:'shrink' missing",
        ],
        visual_policy=VisualPolicy.MEDIA_REQUIRED,
    )
    assert repaired.visual_kind == "image"
    assert len(repaired.bullets) <= 4
    assert repaired.layout_hint in {
        "content-two-column",
        "content-showcase",
        "content-icon-rows",
    }


def test_candidate_variant_specs_and_fallback_research_brief_should_stay_deterministic() -> None:
    variants = candidate_variant_specs(
        slide_no=3, round_no=2, worker_count=3, layout="content-showcase"
    )
    assert [item["worker"] for item in variants] == [1, 2, 3]
    assert all(item["layout_anchor"] == "content-showcase" for item in variants)

    brief = fallback_research_brief(
        topic="Circular Economy",
        template_style="default",
        target_slide_count=4,
    )
    assert brief["page_focus"][0].startswith("Circular Economy:")
    assert brief["effective_template_style"] == "default"
