from __future__ import annotations

import asyncio
import threading
from typing import Any

from .js_contract import load_js_api_contract


class RunRuntimeStateMixin:
    def _initialize_runtime_state(self) -> None:
        def dedupe_preserve_order(items: list[str]) -> list[str]:
            seen: set[str] = set()
            ordered: list[str] = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
            return ordered

        self._timeout_lock = threading.Lock()
        self._timeout_streak = 0
        self._last_timeout_monotonic = 0.0
        self._run_budget_lock = threading.Lock()
        self._run_llm_call_counts: dict[str, int] = {}
        self._run_llm_call_limits: dict[str, int] = {}
        self._asset_context_lock = threading.Lock()
        self._asset_search_context_stack: list[dict[str, Any]] = []
        self._run_asset_keys: dict[str, set[str]] = {}
        self._background_loop: asyncio.AbstractEventLoop | None = None
        self._background_loop_thread: threading.Thread | None = None
        self._background_loop_lock = threading.Lock()
        self._js_api_contract = load_js_api_contract(
            dedupe_preserve_order=dedupe_preserve_order
        )
