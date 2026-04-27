from __future__ import annotations

from .content_primitives_client import LLMContentPrimitivesMixin
from .longform_drafting_client import LLMLongFormDraftingMixin
from .longform_planning_client import LLMLongFormPlanningMixin
from .outline_normalization import LLMOutlineNormalizationMixin
from .outline_prompt_client import LLMOutlinePromptMixin
from .response_formats import LLMStructuredOutputMixin
from .slide_codegen_client import LLMSlideCodegenMixin
from .slide_response_parsers import LLMSlideResponseParsingMixin
from .slide_spec_client import LLMSlideSpecMixin
from .transport import LLMTransportMixin


class OpenAICompatibleLLMClient(
    LLMOutlinePromptMixin,
    LLMLongFormPlanningMixin,
    LLMLongFormDraftingMixin,
    LLMContentPrimitivesMixin,
    LLMSlideCodegenMixin,
    LLMSlideSpecMixin,
    LLMSlideResponseParsingMixin,
    LLMOutlineNormalizationMixin,
    LLMStructuredOutputMixin,
    LLMTransportMixin,
):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        api_style: str = "openai_chat",
        timeout_sec: float = 60.0,
        outline_temperature: float = 0.3,
        slide_temperature: float = 0.6,
        outline_structured_output: bool = True,
        sanitize_think_tags: bool = True,
        json_repair_retry: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_style = api_style
        self.timeout_sec = timeout_sec
        self.outline_temperature = outline_temperature
        self.slide_temperature = slide_temperature
        self.outline_structured_output = outline_structured_output
        self.sanitize_think_tags = bool(sanitize_think_tags)
        self.json_repair_retry = max(0, int(json_repair_retry))
