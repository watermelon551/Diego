from __future__ import annotations

from ._compat import maybe_warn_legacy_import
from .llm import (
    GeneratedSlide,
    LLMClient,
    LLMEmptyResponseError,
    LLMTimeoutError,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    OutlineFormatError,
    SlideSpec,
)
from .llm.parsing import _extract_json_object

maybe_warn_legacy_import(legacy="service.llm_client", replacement="service.llm")

__all__ = [
    "GeneratedSlide",
    "LLMClient",
    "LLMEmptyResponseError",
    "LLMTimeoutError",
    "MockLLMClient",
    "OpenAICompatibleLLMClient",
    "OutlineFormatError",
    "SlideSpec",
    "_extract_json_object",
]
