from __future__ import annotations

from typing import Any

import httpx

from ..models import OutlineNode
from ..run.types import TemplateAssetError
from .asset_provider_search_mixin import AssetProviderSearchMixin
from .asset_query_planning_mixin import AssetQueryPlanningMixin
from .asset_resolution_mixin import AssetResolutionMixin


class TemplateAssetSearchMixin(
    AssetQueryPlanningMixin,
    AssetProviderSearchMixin,
    AssetResolutionMixin,
):
    def _fetch_slot_asset(
        self,
        *,
        query: str,
        slot_type: str,
        node: OutlineNode,
        slide_no: int,
        rel_id: str,
        search_context: dict[str, Any] | None = None,
        used_asset_keys: set[str] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        provider = self.settings.asset_provider.lower().strip()
        normalized_slot = str(slot_type or "image").strip().lower() or "image"
        if provider == "mock":
            return (
                self._build_slot_png_bytes(node=node, slot_type=normalized_slot, slide_no=slide_no, rel_id=rel_id),
                "png",
                {"provider": "mock", "source": "mock", "query": query, "key": f"mock:{slide_no}:{rel_id}:{normalized_slot}"},
            )
        if provider == "none":
            raise TemplateAssetError("asset provider is disabled")

        providers = self._asset_provider_chain(provider)
        if not providers:
            raise TemplateAssetError(f"no configured asset providers for {provider}")

        ctx = search_context if isinstance(search_context, dict) else {}
        queries = self._build_asset_query_candidates(
            query=query,
            node=node,
            slide_no=slide_no,
            slot_type=normalized_slot,
            search_context=ctx,
        )
        seen_used = {str(item).strip() for item in (used_asset_keys or set()) if str(item).strip()}
        all_candidates: list[dict[str, Any]] = []
        all_candidates.extend(self._collect_project_asset_candidates(search_context=ctx, queries=queries, slot_type=normalized_slot))

        last_error: Exception | None = None
        per_query = 4
        for name in providers:
            for _ in range(max(1, self.settings.asset_max_retries)):
                try:
                    all_candidates.extend(
                        self._search_provider_assets(
                            provider=name,
                            queries=queries,
                            slot_type=normalized_slot,
                            per_query=per_query,
                        )
                    )
                    break
                except Exception as exc:  # noqa: PERF203
                    last_error = exc
                    continue

        if not all_candidates:
            raise TemplateAssetError(f"asset fetch failed for query={query!r}: {last_error}")

        ranked = self._rank_asset_candidates(
            candidates=all_candidates,
            queries=queries,
            slot_type=normalized_slot,
            search_context=ctx,
            used_asset_keys=seen_used,
        )
        download_error: Exception | None = None
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            for candidate in ranked[:16]:
                key = str(candidate.get("key", "")).strip()
                if key and key in seen_used:
                    continue
                try:
                    asset_bytes, ext = self._resolve_candidate_asset_bytes(candidate=candidate, client=client)
                    meta = {
                        "key": key or str(candidate.get("url", "")).strip() or str(candidate.get("path", "")).strip(),
                        "provider": str(candidate.get("provider", "")).strip(),
                        "source": str(candidate.get("source", "")).strip() or "public",
                        "query": str(candidate.get("query", "")).strip() or query,
                        "slot_type": normalized_slot,
                    }
                    return asset_bytes, ext, meta
                except Exception as exc:  # noqa: PERF203
                    download_error = exc
                    continue
        raise TemplateAssetError(f"asset fetch failed for query={query!r}: {download_error or last_error}")
