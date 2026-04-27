from __future__ import annotations

from pathlib import Path
from typing import Any

from ....models import OutlineNode
from ....run.types import ChartPlan
from ..asset_rewrite import (
    active_asset_search_context,
    build_asset_query,
    build_slot_png_bytes,
    ensure_image_content_types,
    relative_target,
    rewrite_template_image_icon_assets,
)
from ..chart_rewrite import (
    build_chart_plan_from_bullets,
    extract_chart_facts,
    rewrite_chart_cache_points,
    rewrite_chart_xml_content,
    rewrite_related_chart_xml,
)
from ..layout_reflow import analyze_and_reflow_template_layout
from ..slot_mapping import extract_picture_slots
from ..xml_rewrite import (
    remove_ranges,
    rewrite_template_media_metadata,
    rewrite_template_table_cells,
    rewrite_template_text_runs,
    xml_attr_escape,
    xml_escape,
    xml_unescape,
)


class TemplateSemanticRewriteMixin:
    def _chart_plan_from_outline_bullets(
        self, *, node: OutlineNode, source_refs: list[str]
    ) -> ChartPlan:
        return build_chart_plan_from_bullets(node=node, source_refs=source_refs)

    def _chart_facts_from_outline_bullets(
        self, *, node: OutlineNode, source_refs: list[str]
    ) -> list[Any]:
        return extract_chart_facts(node=node, source_refs=source_refs)

    def _rewrite_template_slide_semantics(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        node: OutlineNode,
        slide_no: int,
        chart_plan: ChartPlan,
    ) -> dict[str, Any]:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        content = self._rewrite_template_text_runs(content=content, node=node)
        content = self._rewrite_template_table_cells(content=content, node=node)
        content = self._rewrite_template_media_metadata(
            content=content,
            node=node,
            slide_no=slide_no,
        )
        slide_xml.write_text(content, encoding="utf-8")
        self._rewrite_template_image_icon_assets(
            unpacked=unpacked,
            slide_xml=slide_xml,
            node=node,
            slide_no=slide_no,
        )
        chart_report = self._rewrite_related_chart_xml(
            unpacked=unpacked,
            slide_xml=slide_xml,
            node=node,
            chart_plan=chart_plan,
        )
        layout_report = self._analyze_and_reflow_template_layout(
            slide_xml=slide_xml,
            slide_no=slide_no,
        )
        return {"chart": chart_report, "layout": layout_report}

    def _rewrite_template_text_runs(self, *, content: str, node: OutlineNode) -> str:
        return rewrite_template_text_runs(
            content=content,
            node=node,
            xml_escape=self._xml_escape,
        )

    def _rewrite_template_table_cells(self, *, content: str, node: OutlineNode) -> str:
        return rewrite_template_table_cells(
            content=content,
            node=node,
            xml_escape=self._xml_escape,
        )

    def _rewrite_template_media_metadata(
        self, *, content: str, node: OutlineNode, slide_no: int
    ) -> str:
        return rewrite_template_media_metadata(
            content=content,
            node=node,
            slide_no=slide_no,
            parse_xml_attrs=self._parse_xml_attrs,
            xml_escape=self._xml_escape,
            xml_attr_escape=self._xml_attr_escape,
        )

    def _rewrite_template_image_icon_assets(
        self, *, unpacked: Path, slide_xml: Path, node: OutlineNode, slide_no: int
    ) -> None:
        rewrite_template_image_icon_assets(
            unpacked=unpacked,
            slide_xml=slide_xml,
            node=node,
            slide_no=slide_no,
            extract_picture_slots=self._extract_picture_slots,
            remove_ranges=self._remove_ranges,
            active_asset_search_context=self._active_asset_search_context,
            parse_xml_attrs=self._parse_xml_attrs,
            build_asset_query=self._build_asset_query,
            fetch_slot_asset=self._fetch_slot_asset,
            relative_target=self._relative_target,
            xml_attr_escape=self._xml_attr_escape,
            ensure_image_content_types=self._ensure_image_content_types,
            run_asset_keys_snapshot=getattr(self, "_run_asset_keys_snapshot", None),
            remember_run_asset_key=getattr(self, "_remember_run_asset_key", None),
        )

    def _extract_picture_slots(self, slide_text: str) -> list[dict[str, Any]]:
        return extract_picture_slots(slide_text)

    def _remove_ranges(self, text: str, ranges: list[tuple[int, int]]) -> str:
        return remove_ranges(text, ranges)

    def _active_asset_search_context(self) -> dict[str, Any]:
        return active_asset_search_context(
            getattr(self, "_get_active_asset_search_context", None)
        )

    def _build_asset_query(
        self, *, node: OutlineNode, slot_type: str, slide_no: int
    ) -> str:
        return build_asset_query(node=node, slot_type=slot_type, slide_no=slide_no)

    def _build_slot_png_bytes(
        self, *, node: OutlineNode, slot_type: str, slide_no: int, rel_id: str
    ) -> bytes:
        return build_slot_png_bytes(
            node=node,
            slot_type=slot_type,
            slide_no=slide_no,
            rel_id=rel_id,
        )

    def _ensure_image_content_types(self, *, unpacked: Path, exts: set[str]) -> None:
        ensure_image_content_types(unpacked=unpacked, exts=exts)

    def _relative_target(self, *, from_dir: Path, to_path: Path) -> str:
        return relative_target(from_dir=from_dir, to_path=to_path)

    def _rewrite_related_chart_xml(
        self,
        *,
        unpacked: Path,
        slide_xml: Path,
        node: OutlineNode,
        chart_plan: ChartPlan,
    ) -> dict[str, Any]:
        return rewrite_related_chart_xml(
            unpacked=unpacked,
            slide_xml=slide_xml,
            node=node,
            chart_plan=chart_plan,
            parse_xml_attrs=self._parse_xml_attrs,
            rewrite_chart_xml_content=lambda **kwargs: self._rewrite_chart_xml_content(
                **kwargs
            ),
        )

    def _rewrite_chart_xml_content(
        self, *, chart_xml: str, node: OutlineNode, chart_plan: ChartPlan
    ) -> str:
        return rewrite_chart_xml_content(
            chart_xml=chart_xml,
            node=node,
            chart_plan=chart_plan,
            xml_escape=self._xml_escape,
            rewrite_chart_cache_points=lambda **kwargs: self._rewrite_chart_cache_points(
                **kwargs
            ),
        )

    def _rewrite_chart_cache_points(
        self, *, chart_xml: str, cache_tag: str, value_tag: str, values: list[str]
    ) -> str:
        return rewrite_chart_cache_points(
            chart_xml=chart_xml,
            cache_tag=cache_tag,
            value_tag=value_tag,
            values=values,
            xml_escape=self._xml_escape,
        )

    def _analyze_and_reflow_template_layout(
        self, *, slide_xml: Path, slide_no: int
    ) -> dict[str, Any]:
        content = slide_xml.read_text(encoding="utf-8", errors="ignore")
        rewritten, report = analyze_and_reflow_template_layout(
            content=content,
            slide_no=slide_no,
        )
        if rewritten != content:
            slide_xml.write_text(rewritten, encoding="utf-8")
        return report

    def _xml_escape(self, text: str) -> str:
        return xml_escape(text)

    def _xml_unescape(self, text: str) -> str:
        return xml_unescape(text)

    def _xml_attr_escape(self, text: str) -> str:
        return xml_attr_escape(text)
