from __future__ import annotations

from service.llm.normalization_runtime.outline_mixin import (
    LLMOutlineDocumentNormalizationMixin,
)
from service.llm.pptd_skill_guidance import PPTD_OUTLINE_QUALITY_GUIDANCE
from service.models import OutlineDocument, OutlineNode, SlidePageType


class _OutlineNormalizer(LLMOutlineDocumentNormalizationMixin):
    pass


def test_pptd_outline_guidance_describes_page_plan_bullets() -> None:
    assert "PPTD page plan" in PPTD_OUTLINE_QUALITY_GUIDANCE
    assert "content-comparison" in PPTD_OUTLINE_QUALITY_GUIDANCE
    assert "GBN:" in PPTD_OUTLINE_QUALITY_GUIDANCE
    assert "content-timeline" in PPTD_OUTLINE_QUALITY_GUIDANCE
    assert "content-stat-callout" in PPTD_OUTLINE_QUALITY_GUIDANCE
    assert "| 指标 | GBN | SR |" in PPTD_OUTLINE_QUALITY_GUIDANCE


def test_pptd_outline_normalizer_splits_inline_gbn_sr_comparison() -> None:
    outline = OutlineDocument(
        version=1,
        summary="数据链路层课程",
        nodes=[
            OutlineNode(
                title="数据链路层",
                bullets=["课程入口"],
                page_type=SlidePageType.COVER,
            ),
            OutlineNode(
                title="目录",
                bullets=["协议对比"],
                page_type=SlidePageType.TOC,
            ),
            OutlineNode(
                title="GBN与SR协议：机制与对比",
                bullets=[
                    "GBN(回退N帧)：发送窗口与累积确认机制",
                    "SR(选择重传)：接收窗口与独立确认机制",
                    "性能对比：吞吐量、信道利用率、缓冲区需求",
                ],
                page_type=SlidePageType.CONTENT,
                layout_hint="content-two-column",
            ),
            OutlineNode(
                title="总结",
                bullets=["协议选择"],
                page_type=SlidePageType.SUMMARY,
            ),
        ],
    )

    fitted = _OutlineNormalizer()._fit_outline(
        outline,
        topic="数据链路层",
        target_slide_count=4,
        template_style="education courseware",
    )

    node = fitted.nodes[2]
    assert node.layout_hint == "content-comparison"
    assert node.bullets[:2] == ["GBN：", "发送窗口与累积确认机制"]
    assert "SR：" in node.bullets
    assert "接收窗口与独立确认机制" in node.bullets
    assert "GBN(回退N帧)" not in " ".join(node.bullets)


def test_pptd_outline_normalizer_preserves_existing_grouped_comparison() -> None:
    outline = OutlineDocument(
        version=1,
        summary="协议课",
        nodes=[
            OutlineNode(title="封面", page_type=SlidePageType.COVER),
            OutlineNode(title="目录", page_type=SlidePageType.TOC),
            OutlineNode(
                title="GBN vs SR",
                bullets=["GBN：", "批量重传未确认帧", "SR：", "只重传出错帧"],
                page_type=SlidePageType.CONTENT,
                layout_hint="content-showcase",
            ),
            OutlineNode(title="总结", page_type=SlidePageType.SUMMARY),
        ],
    )

    fitted = _OutlineNormalizer()._fit_outline(
        outline,
        topic="数据链路层",
        target_slide_count=4,
        template_style="education courseware",
    )

    node = fitted.nodes[2]
    assert node.layout_hint == "content-comparison"
    assert node.bullets == ["GBN：", "批量重传未确认帧", "SR：", "只重传出错帧"]
