from __future__ import annotations

from .mock_longform_content_mixin import MockLongFormContentMixin
from .mock_outline_generation_mixin import MockOutlineGenerationMixin
from .mock_slide_generation_mixin import MockSlideGenerationMixin
from .mock_slide_spec_mixin import MockSlideSpecMixin


class MockLLMClient(
    MockOutlineGenerationMixin,
    MockLongFormContentMixin,
    MockSlideGenerationMixin,
    MockSlideSpecMixin,
):
    pass
