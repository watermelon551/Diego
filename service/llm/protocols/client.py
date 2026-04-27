from __future__ import annotations

from typing import Protocol

from .content import LLMContentProtocol
from .outline import LLMOutlineProtocol
from .slide import LLMSlideProtocol


class LLMClient(
    LLMOutlineProtocol,
    LLMContentProtocol,
    LLMSlideProtocol,
    Protocol,
):
    pass

