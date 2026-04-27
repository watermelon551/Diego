from __future__ import annotations

from typing import Any

from ....models import OutlineNode
from ....run.types import ChartPlan
from ...asset_search_mixin import TemplateAssetSearchMixin
from .semantic_rewrite_mixin import TemplateSemanticRewriteMixin
from .structure_runtime_mixin import TemplateStructureRuntimeMixin


class TemplateOpsMixin(
    TemplateStructureRuntimeMixin,
    TemplateSemanticRewriteMixin,
    TemplateAssetSearchMixin,
):
    def _build_chart_plan_from_bullets(
        self, *, node: OutlineNode, source_refs: list[str]
    ) -> ChartPlan:
        return self._chart_plan_from_outline_bullets(node=node, source_refs=source_refs)

    def _extract_chart_facts(self, *, node: OutlineNode, source_refs: list[str]) -> Any:
        return self._chart_facts_from_outline_bullets(
            node=node,
            source_refs=source_refs,
        )


__all__ = ["TemplateOpsMixin"]
