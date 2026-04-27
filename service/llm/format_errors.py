from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OutlineFormatError(RuntimeError):
    category: str
    details: list[str]
    raw_response: str

    def __post_init__(self) -> None:
        super().__init__(f"outline {self.category} error: {'; '.join(self.details[:3])}")


@dataclass
class LongFormFormatError(RuntimeError):
    category: str
    details: list[str]
    raw_response: str

    def __post_init__(self) -> None:
        super().__init__(
            f"longform {self.category} error: {'; '.join(self.details[:3])}"
        )


@dataclass
class LLMTimeoutError(RuntimeError):
    attempts: int
    reason: str
    phase: str = "outline"

    def __post_init__(self) -> None:
        message = self.reason.strip() or "request timed out"
        super().__init__(f"{self.phase} timeout after {self.attempts} attempts: {message}")


@dataclass
class LLMEmptyResponseError(RuntimeError):
    phase: str
    reason: str = "empty or invalid model response"

    def __post_init__(self) -> None:
        super().__init__(f"{self.phase}: {self.reason}")
