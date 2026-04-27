from __future__ import annotations

from typing import Any

from ..llm import LLMClient
from ..rag import StratumindSearchClient
from .orchestrator_bootstrap import (
    RunRuntimeConfigMixin,
    RunRuntimeGatesMixin,
    RunRuntimeServicesMixin,
    RunRuntimeStateMixin,
)


class RunOrchestratorBootstrapMixin(
    RunRuntimeConfigMixin,
    RunRuntimeGatesMixin,
    RunRuntimeStateMixin,
    RunRuntimeServicesMixin,
):
    def _initialize_runtime(
        self,
        *,
        llm_client: LLMClient,
        rag_client: StratumindSearchClient | None,
    ) -> None:
        self._initialize_runtime_config(llm_client=llm_client, rag_client=rag_client)
        self._initialize_runtime_gates()
        self._initialize_runtime_state()
        self._initialize_runtime_services()

    def __getattr__(self, name: str) -> Any:
        if name in self._legacy_aliases:
            return self._legacy_aliases[name]
        try:
            return getattr(self._support, name)
        except AttributeError as exc:
            raise AttributeError(
                f"{type(self).__name__!s} has no attribute {name!r}"
            ) from exc


__all__ = ["RunOrchestratorBootstrapMixin"]
