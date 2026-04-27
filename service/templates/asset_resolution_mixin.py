from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Any

import httpx

from ..run.types import TemplateAssetError


class AssetResolutionMixin:
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
            score += self._orientation_score(candidate=candidate, slot_type=slot_type)
            overlap = sum(1 for term in context_terms if term in text)
            score += min(4.0, overlap * 0.35)
            q = str(candidate.get("query", "")).strip().lower()
            score += max(0.0, 1.2 - 0.25 * float(query_rank.get(q, 4)))
            jitter_key = (
                key
                or str(candidate.get("url", "")).strip()
                or str(candidate.get("path", "")).strip()
            )
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
        stop = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "slide",
            "presentation",
            "photo",
            "image",
        }
        words = re.findall(r"[a-z0-9]{3,}", text.lower())
        return {item for item in words if item not in stop}

    def _resolve_candidate_asset_bytes(
        self, *, candidate: dict[str, Any], client: httpx.Client
    ) -> tuple[bytes, str]:
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
        ext = self._guess_image_ext(
            content_type=resp.headers.get("content-type", ""), url=url
        )
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
