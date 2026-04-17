from __future__ import annotations

from typing import Any


class AssetResolver:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def build_asset_search_context(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.runtime._build_asset_search_context(*args, **kwargs)

    def push_asset_search_context(self, context: dict[str, Any]) -> None:
        self.runtime._push_asset_search_context(context)

    def pop_asset_search_context(self) -> None:
        self.runtime._pop_asset_search_context()
