from __future__ import annotations

from typing import Any

import httpx

from ..run.types import TemplateAssetError


class AssetProviderSearchMixin:
    def _search_provider_assets(
        self, *, provider: str, queries: list[str], slot_type: str, per_query: int
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for query in queries[:4]:
            if provider == "unsplash":
                out.extend(
                    self._search_unsplash_assets(
                        query=query, slot_type=slot_type, per_page=per_query
                    )
                )
            elif provider == "pexels":
                out.extend(
                    self._search_pexels_assets(
                        query=query, slot_type=slot_type, per_page=per_query
                    )
                )
        return out

    def _fetch_unsplash_asset(self, *, query: str, slot_type: str) -> tuple[bytes, str]:
        result = self._search_unsplash_assets(query=query, slot_type=slot_type, per_page=1)
        if not result:
            raise TemplateAssetError("unsplash returned no results")
        candidate = result[0]
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            return self._resolve_candidate_asset_bytes(candidate=candidate, client=client)

    def _search_unsplash_assets(
        self, *, query: str, slot_type: str, per_page: int
    ) -> list[dict[str, Any]]:
        key = self.settings.unsplash_access_key.strip()
        if not key:
            raise TemplateAssetError("missing UNSPLASH_ACCESS_KEY")
        orientation = "landscape" if slot_type == "image" else "squarish"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.unsplash.com/search/photos",
                params={
                    "query": query,
                    "per_page": max(1, int(per_page)),
                    "orientation": orientation,
                },
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
        result = self._search_pexels_assets(query=query, slot_type=slot_type, per_page=1)
        if not result:
            raise TemplateAssetError("pexels returned no results")
        candidate = result[0]
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            return self._resolve_candidate_asset_bytes(candidate=candidate, client=client)

    def _search_pexels_assets(
        self, *, query: str, slot_type: str, per_page: int
    ) -> list[dict[str, Any]]:
        key = self.settings.pexels_api_key.strip()
        if not key:
            raise TemplateAssetError("missing PEXELS_API_KEY")
        orientation = "landscape" if slot_type == "image" else "square"
        with httpx.Client(timeout=self.settings.asset_timeout_sec, follow_redirects=True) as client:
            resp = client.get(
                "https://api.pexels.com/v1/search",
                params={
                    "query": query,
                    "per_page": max(1, int(per_page)),
                    "orientation": orientation,
                },
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
