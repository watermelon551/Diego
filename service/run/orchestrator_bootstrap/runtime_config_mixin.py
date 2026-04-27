from __future__ import annotations

import subprocess

from ...llm import LLMClient
from ...rag import StratumindSearchClient


class RunRuntimeConfigMixin:
    def _initialize_runtime_config(
        self,
        *,
        llm_client: LLMClient,
        rag_client: StratumindSearchClient | None,
    ) -> None:
        self.llm_client = llm_client
        self.rag_client = rag_client or StratumindSearchClient(
            base_url=self.settings.stratumind_base_url,
            timeout_sec=self.settings.stratumind_timeout_sec,
        )
        self.subprocess = subprocess
        self.slide_concurrency = max(1, self.settings.slide_concurrency)
        self.slide_retry = max(1, self.settings.slide_retry)
        self.llm_max_retries = max(1, self.settings.llm_max_retries)
        self.outline_timeout_retries = max(0, self.settings.outline_timeout_retries)
        self.outline_timeout_backoff_sec = max(
            0.0, self.settings.outline_timeout_backoff_sec
        )
        self.repair_rounds = max(1, self.settings.repair_rounds)
        self.max_slide_repair_rounds = max(1, self.settings.max_slide_repair_rounds)
        self.llm_request_concurrency = max(
            1, int(getattr(self.settings, "llm_request_concurrency", 6))
        )
        self.slide_candidate_workers = max(
            1, min(5, int(getattr(self.settings, "slide_candidate_workers", 3)))
        )
        self.llm_timeout_jitter_sec = max(
            0.0, float(getattr(self.settings, "llm_timeout_jitter_sec", 0.2))
        )
        self.slide_fatal_early_stop_rounds = max(
            1, int(getattr(self.settings, "slide_fatal_early_stop_rounds", 2))
        )
        self.run_max_llm_calls = max(
            0, int(getattr(self.settings, "run_max_llm_calls", 0))
        )
        self.keep_failed_candidate_js = bool(
            getattr(self.settings, "keep_failed_candidate_js", True)
        )
        self.slide_auto_canonicalize = bool(
            getattr(self.settings, "slide_auto_canonicalize", True)
        )
        self.slide_diag_max_js_lines = max(
            40, int(getattr(self.settings, "slide_diag_max_js_lines", 260))
        )
        self.slide_diag_max_stderr_chars = max(
            2000, int(getattr(self.settings, "slide_diag_max_stderr_chars", 12000))
        )
        self.preview_qa_concurrency = max(
            1,
            int(
                getattr(
                    self.settings, "preview_qa_concurrency", self.slide_concurrency
                )
            ),
        )
        self.asset_fetch_concurrency = max(
            1, int(getattr(self.settings, "asset_fetch_concurrency", 2))
        )
        self.llm_concurrency_build = max(
            1, int(getattr(self.settings, "llm_concurrency_build", 3))
        )
        self.llm_concurrency_evaluate = max(
            1, int(getattr(self.settings, "llm_concurrency_evaluate", 2))
        )
        self.llm_concurrency_repair = max(
            1, int(getattr(self.settings, "llm_concurrency_repair", 1))
        )
        self.timeout_streak_degrade_threshold = max(
            1, int(getattr(self.settings, "timeout_streak_degrade_threshold", 3))
        )
        self.timeout_streak_recover_window_sec = max(
            0.0,
            float(getattr(self.settings, "timeout_streak_recover_window_sec", 120.0)),
        )
