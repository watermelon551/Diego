from service.design.skill_profile import DesignProfile, STYLE_RECIPES
from service.llm.types import GeneratedSlide
from service.models import OutlineNode, SlidePageType
from service.run.types import ChartPlan
from service.slides.skill_slide_renderer import build_toc_items, render_skill_slide_js


def test_build_toc_items_projects_outline_node_details() -> None:
    toc = OutlineNode(
        title="Contents",
        bullets=["3.1 Framing", "3.2 Error Control"],
        page_type=SlidePageType.TOC,
        layout_hint="toc-list",
    )
    nodes = [
        OutlineNode(
            title="Cover",
            bullets=["Opening"],
            page_type=SlidePageType.COVER,
        ),
        toc,
        OutlineNode(
            title="3.1 Framing",
            bullets=["Frame boundaries", "Byte stuffing", "Bit stuffing"],
            page_type=SlidePageType.CONTENT,
        ),
        OutlineNode(
            title="3.2 Error Control",
            bullets=["Detection", "Correction"],
            page_type=SlidePageType.SECTION,
        ),
    ]

    assert build_toc_items(node=toc, outline_nodes=nodes) == [
        {
            "title": "3.1 Framing",
            "details": ["Frame boundaries", "Byte stuffing"],
        },
        {
            "title": "3.2 Error Control",
            "details": ["Detection", "Correction"],
        },
    ]


def test_render_skill_slide_js_includes_toc_item_details() -> None:
    design = DesignProfile(
        palette_name="test",
        theme={
            "primary": "111111",
            "secondary": "333333",
            "accent": "555555",
            "light": "EEEEEE",
            "bg": "FFFFFF",
        },
        title_font="Arial",
        body_font="Arial",
        style=STYLE_RECIPES["soft"],
    )
    toc = OutlineNode(
        title="Contents",
        bullets=["3.1 Framing"],
        page_type=SlidePageType.TOC,
        layout_hint="toc-list",
    )

    js_code = render_skill_slide_js(
        slide_no=2,
        total=4,
        node=toc,
        generated=GeneratedSlide(
            title="Contents",
            bullets=["3.1 Framing"],
            citations=[],
            page_type=SlidePageType.TOC,
            layout_hint="toc-list",
        ),
        design=design,
        chart_plan=ChartPlan(
            has_verified_data=False,
            mode="none",
            labels=[],
            values=[],
            unit="",
            note="",
            source="test",
        ),
        outline_nodes=[
            toc,
            OutlineNode(
                title="3.1 Framing",
                bullets=["Frame boundaries", "Byte stuffing"],
                page_type=SlidePageType.CONTENT,
            ),
        ],
    )

    assert "tocItems" in js_code
    assert "Frame boundaries" in js_code
    assert "Byte stuffing" in js_code
