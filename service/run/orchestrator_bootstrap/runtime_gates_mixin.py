from __future__ import annotations

import threading


class RunRuntimeGatesMixin:
    def _initialize_runtime_gates(self) -> None:
        self._llm_request_gate = threading.BoundedSemaphore(
            self.llm_request_concurrency
        )
        self._llm_phase_build_gate = threading.BoundedSemaphore(
            min(self.llm_request_concurrency, self.llm_concurrency_build)
        )
        self._llm_phase_evaluate_gate = threading.BoundedSemaphore(
            min(self.llm_request_concurrency, self.llm_concurrency_evaluate)
        )
        self._llm_phase_repair_gate = threading.BoundedSemaphore(
            min(self.llm_request_concurrency, self.llm_concurrency_repair)
        )
        self._llm_pressure_gate = threading.BoundedSemaphore(1)
        self._preview_qa_gate = threading.BoundedSemaphore(self.preview_qa_concurrency)
        self._asset_fetch_gate = threading.BoundedSemaphore(
            self.asset_fetch_concurrency
        )
