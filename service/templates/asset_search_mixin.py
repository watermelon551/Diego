from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..models import OutlineNode
from ..run.types import TemplateAssetError


class TemplateAssetSearchMixin:
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

    def _collect_project_asset_candidates(self, *, search_context: dict[str, Any], queries: list[str], slot_type: str) -> list[dict[str, Any]]:
        raw_sources: list[Any] = []
        for key in ("rag_source_ids", "project_asset_urls", "image_candidates", "asset_candidates"):
            value = search_context.get(key)
            if isinstance(value, list):
                raw_sources.extend(value)
        report = search_context.get("research_report")
        if isinstance(report, dict):
            for key in ("image_candidates", "project_assets", "visual_references", "asset_candidates"):
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
        return any(name in host for name in ("unsplash", "pexels", "pixabay", "wikimedia", "imgur"))

    def _looks_local_image_reference(self, value: str) -> bool:
        path_text = str(value or "").strip()
        if not path_text:
            return False
        path = Path(path_text)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return False
        return path.exists() and path.is_file()

    def _search_provider_assets(self, *, provider: str, queries: list[str], slot_type: str, per_query: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for query in queries[:4]:
            if provider == "unsplash":
                out.extend(self._search_unsplash_assets(query=query, slot_type=slot_type, per_page=per_query))
            elif provider == "pexels":
                out.extend(self._search_pexels_assets(query=query, slot_type=slot_type, per_page=per_query))
        return out

    def _fetch_unsplash_asset(self, *, query: str, slot_type: str) -> tuple[bytes, str]:
        # Backward-compatible wrapper used by older call sites.
        result = self._search_unsplash_assets(query=query, slot_type=slot_type, per_page=1)
        if not result:
            raise TemplateAssetError("unsplash returned no results")
        candidate = result[0]
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            return self._resolve_candidate_asset_bytes(candidate=candidate, client=client)

    def _search_unsplash_assets(self, *, query: str, slot_type: str, per_page: int) -> list[dict[str, Any]]:
        key = self.settings.unsplash_access_key.strip()
        if not key:
            raise TemplateAssetError("missing UNSPLASH_ACCESS_KEY")
        orientation = "landscape" if slot_type == "image" else "squarish"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": max(1, int(per_page)), "orientation": orientation},
                headers={"Authorization": f"Client-ID {key}"},
            )
            resp.raise_for_status()
            payload = resp.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []
            if not results:
                return []
            out: list[dict[str, Any]] = []
            for row in results:
                if not isinstance(row, dict):
                    continue
                urls = row.get("urls", {}) if isinstance(row.get("urls"), dict) else {}
                image_url = urls.get("regular") or urls.get("full") or urls.get("small")
                if not image_url:
                    continue
                text = " ".join(
                    [
                        str(row.get("alt_description", "")).strip(),
                        str(row.get("description", "")).strip(),
                    ]
                ).strip()
                key_id = str(row.get("id", "")).strip() or str(image_url).strip()
                out.append(
                    {
                        "key": f"unsplash:{key_id}",
                        "provider": "unsplash",
                        "source": "public",
                        "query": query,
                        "url": str(image_url),
                        "text": text,
                        "width": row.get("width"),
                        "height": row.get("height"),
                    }
                )
            return out

    def _fetch_pexels_asset(self, *, query: str, slot_type: str) -> tuple[bytes, str]:
        # Backward-compatible wrapper used by older call sites.
        result = self._search_pexels_assets(query=query, slot_type=slot_type, per_page=1)
        if not result:
            raise TemplateAssetError("pexels returned no results")
        candidate = result[0]
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            return self._resolve_candidate_asset_bytes(candidate=candidate, client=client)

    def _search_pexels_assets(self, *, query: str, slot_type: str, per_page: int) -> list[dict[str, Any]]:
        key = self.settings.pexels_api_key.strip()
        if not key:
            raise TemplateAssetError("missing PEXELS_API_KEY")
        orientation = "landscape" if slot_type == "image" else "square"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": max(1, int(per_page)), "orientation": orientation},
                headers={"Authorization": key},
            )
            resp.raise_for_status()
            payload = resp.json()
            photos = payload.get("photos", []) if isinstance(payload, dict) else []
            if not photos:
                return []
            out: list[dict[str, Any]] = []
            for row in photos:
                if not isinstance(row, dict):
                    continue
                src = row.get("src", {}) if isinstance(row.get("src"), dict) else {}
                image_url = src.get("large2x") or src.get("large") or src.get("original")
                if not image_url:
                    continue
                text = " ".join(
                    [
                        str(row.get("alt", "")).strip(),
                        str(row.get("photographer", "")).strip(),
                    ]
                ).strip()
                key_id = str(row.get("id", "")).strip() or str(image_url).strip()
                out.append(
                    {
                        "key": f"pexels:{key_id}",
                        "provider": "pexels",
                        "source": "public",
                        "query": query,
                        "url": str(image_url),
                        "text": text,
                        "width": row.get("width"),
                        "height": row.get("height"),
                    }
                )
            return out

    def _rank_asset_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        queries: list[str],
        slot_type: str,
        search_context: dict[str, Any],
        used_asset_keys: set[str],
    ) -> list[dict[str, Any]]:
        topic = str(search_context.get("topic", "")).strip()
        page_focus = str(search_context.get("page_focus", "")).strip()
        context_terms = self._tokenize_terms(" ".join([topic, page_focus, " ".join(queries)]))
        query_rank = {query.lower(): idx for idx, query in enumerate(queries)}
        scored: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            key = str(candidate.get("key", "")).strip()
            if key and key in used_asset_keys:
                continue
            text = " ".join(
                [
                    str(candidate.get("text", "")).strip(),
                    str(candidate.get("query", "")).strip(),
                    str(candidate.get("url", "")).strip(),
                    str(candidate.get("path", "")).strip(),
                ]
            ).lower()
            score = 0.0
            if str(candidate.get("source", "")).strip().lower() == "project":
                score += 6.0
            ratio_score = self._orientation_score(candidate=candidate, slot_type=slot_type)
            score += ratio_score
            overlap = sum(1 for term in context_terms if term in text)
            score += min(4.0, overlap * 0.35)
            q = str(candidate.get("query", "")).strip().lower()
            score += max(0.0, 1.2 - 0.25 * float(query_rank.get(q, 4)))
            # Stable tiny jitter to avoid deterministic lock on one public image.
            jitter_key = key or str(candidate.get("url", "")).strip() or str(candidate.get("path", "")).strip()
            score += (zlib.crc32(jitter_key.encode("utf-8", errors="ignore")) % 17) / 100.0
            scored.append((score, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored]

    def _orientation_score(self, *, candidate: dict[str, Any], slot_type: str) -> float:
        width = candidate.get("width")
        height = candidate.get("height")
        try:
            w = float(width)
            h = float(height)
        except (TypeError, ValueError):
            return 0.4
        if w <= 0 or h <= 0:
            return 0.0
        ratio = w / h
        if slot_type == "image":
            if ratio >= 1.2:
                return 2.0
            if ratio >= 0.95:
                return 0.6
            return -0.6
        if slot_type == "icon":
            if 0.85 <= ratio <= 1.2:
                return 1.8
            return -0.4
        return 0.5

    def _tokenize_terms(self, text: str) -> set[str]:
        stop = {"the", "and", "for", "with", "from", "that", "this", "slide", "presentation", "photo", "image"}
        words = re.findall(r"[a-z0-9]{3,}", text.lower())
        return {item for item in words if item not in stop}

    def _resolve_candidate_asset_bytes(self, *, candidate: dict[str, Any], client: httpx.Client) -> tuple[bytes, str]:
        local_path = str(candidate.get("path", "")).strip()
        if local_path:
            path = Path(local_path)
            if not path.exists() or not path.is_file():
                raise TemplateAssetError(f"project asset path missing: {local_path}")
            content = path.read_bytes()
            if not content:
                raise TemplateAssetError(f"project asset is empty: {local_path}")
            ext = path.suffix.lower().lstrip(".")
            if ext == "jpeg":
                ext = "jpg"
            if ext not in {"png", "jpg", "webp"}:
                ext = "jpg"
            return content, ext
        url = str(candidate.get("url", "")).strip()
        if not url:
            raise TemplateAssetError("candidate missing url/path")
        return self._download_asset(client=client, url=url)

    def _download_asset(self, *, client: httpx.Client, url: str) -> tuple[bytes, str]:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content
        if not content:
            raise TemplateAssetError("downloaded asset is empty")
        ext = self._guess_image_ext(content_type=resp.headers.get("content-type", ""), url=url)
        return content, ext

    def _guess_image_ext(self, *, content_type: str, url: str) -> str:
        lowered = content_type.lower()
        if "png" in lowered:
            return "png"
        if "jpeg" in lowered or "jpg" in lowered:
            return "jpg"
        if "webp" in lowered:
            return "webp"
        suffix = Path(url.split("?", 1)[0]).suffix.lower().lstrip(".")
        if suffix in {"png", "jpg", "jpeg", "webp"}:
            return "jpg" if suffix == "jpeg" else suffix
        return "jpg"
