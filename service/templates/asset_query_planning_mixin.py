from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..models import OutlineNode


class AssetQueryPlanningMixin:
    def _asset_provider_chain(self, provider: str) -> list[str]:
        if provider == "unsplash":
            return ["unsplash"]
        if provider == "pexels":
            return ["pexels"]
        if provider == "auto":
            order: list[str] = []
            if self.settings.unsplash_access_key:
                order.append("unsplash")
            if self.settings.pexels_api_key:
                order.append("pexels")
            return order
        return []

    def _build_asset_query_candidates(
        self,
        *,
        query: str,
        node: OutlineNode,
        slide_no: int,
        slot_type: str,
        search_context: dict[str, Any],
    ) -> list[str]:
        topic = str(search_context.get("topic", "")).strip()
        page_focus = str(search_context.get("page_focus", "")).strip()
        intent = str(search_context.get("style_intent", "")).strip()
        bullets = [str(item).strip() for item in (node.bullets or []) if str(item).strip()]
        seeds = [
            query,
            f"{topic} {node.title}".strip(),
            f"{node.title} {bullets[0]}".strip() if bullets else node.title,
            f"{topic} {page_focus}".strip(),
            f"{node.title} {intent}".strip(),
        ]
        if len(bullets) > 1:
            seeds.append(f"{node.title} {bullets[1]}".strip())
        if slot_type == "icon":
            seeds = [f"{item} flat icon minimal".strip() for item in seeds if item.strip()]
        elif slot_type == "logo":
            seeds = [f"{item} company logo".strip() for item in seeds if item.strip()]
        else:
            seeds = [f"{item} presentation photo".strip() for item in seeds if item.strip()]
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in seeds:
            normalized = re.sub(r"\s+", " ", str(raw or "").strip())
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(normalized)
        fallback = self._build_asset_query(node=node, slot_type=slot_type, slide_no=slide_no)
        if not cleaned:
            return [fallback]
        if fallback.lower() not in seen:
            cleaned.insert(0, fallback)
        return cleaned[:6]

    def _collect_project_asset_candidates(
        self, *, search_context: dict[str, Any], queries: list[str], slot_type: str
    ) -> list[dict[str, Any]]:
        raw_sources: list[Any] = []
        for key in (
            "rag_source_ids",
            "project_asset_urls",
            "image_candidates",
            "asset_candidates",
        ):
            value = search_context.get(key)
            if isinstance(value, list):
                raw_sources.extend(value)
        report = search_context.get("research_report")
        if isinstance(report, dict):
            for key in (
                "image_candidates",
                "project_assets",
                "visual_references",
                "asset_candidates",
            ):
                value = report.get(key)
                if isinstance(value, list):
                    raw_sources.extend(value)
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_sources:
            url = ""
            local_path = ""
            text = ""
            if isinstance(item, str):
                value = item.strip()
                if not value:
                    continue
                if self._looks_http_image_reference(value):
                    url = value
                elif self._looks_local_image_reference(value):
                    local_path = value
                text = value
            elif isinstance(item, dict):
                for field in ("url", "image_url", "src", "download_url"):
                    candidate = str(item.get(field, "")).strip()
                    if self._looks_http_image_reference(candidate):
                        url = candidate
                        break
                if not url:
                    for field in ("path", "file", "local_path"):
                        candidate = str(item.get(field, "")).strip()
                        if self._looks_local_image_reference(candidate):
                            local_path = candidate
                            break
                text = " ".join(
                    [
                        str(item.get("caption", "")).strip(),
                        str(item.get("title", "")).strip(),
                        str(item.get("query", "")).strip(),
                    ]
                ).strip()
            else:
                continue

            key = (url or local_path).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "key": f"project:{key}",
                    "provider": "project",
                    "source": "project",
                    "query": queries[0] if queries else "",
                    "url": url,
                    "path": local_path,
                    "text": text,
                    "slot_type": slot_type,
                }
            )
        return candidates

    def _looks_http_image_reference(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if not text.lower().startswith(("http://", "https://")):
            return False
        parsed = urlparse(text)
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
            return True
        host = parsed.netloc.lower()
        return any(
            name in host for name in ("unsplash", "pexels", "pixabay", "wikimedia", "imgur")
        )

    def _looks_local_image_reference(self, value: str) -> bool:
        path_text = str(value or "").strip()
        if not path_text:
            return False
        path = Path(path_text)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return False
        return path.exists() and path.is_file()
