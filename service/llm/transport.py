from __future__ import annotations

from .transport_runtime import (
    LLMAnthropicTransportMixin,
    LLMJsonRepairMixin,
    LLMOpenAIChatTextMixin,
    LLMOpenAIStreamMixin,
    LLMResponseTextMixin,
)


class LLMTransportMixin(
    LLMJsonRepairMixin,
    LLMOpenAIChatTextMixin,
    LLMOpenAIStreamMixin,
    LLMAnthropicTransportMixin,
    LLMResponseTextMixin,
):
    """Thin transport facade layered over explicit provider/runtime mixins."""


__all__ = ["LLMTransportMixin"]
