from __future__ import annotations

import re
from typing import Any

from ..parsing import _extract_json_object


class LLMJsonRepairMixin:
    async def _extract_json_object_with_repair(
        self,
        *,
        text: str,
        expected_keys: list[str],
        temperature: float,
    ) -> dict[str, Any]:
        try:
            return _extract_json_object(text)
        except Exception as exc:
            last_exc: Exception = exc

        if self.json_repair_retry <= 0:
            raise last_exc

        expected = ", ".join(expected_keys)
        prompt = (
            "Return one valid JSON object only. Do not include markdown fences, explanations, or tags.\n"
            f"Required keys: {expected}\n"
            f"Previous parse error: {str(last_exc)[:500]}\n"
            f"Raw model output:\n{text[:20000]}"
        )
        repaired_text = text
        for _ in range(self.json_repair_retry):
            repaired_text = await self._chat_text(
                messages=[
                    {"role": "system", "content": "You are a strict JSON repair assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
            )
            try:
                return _extract_json_object(repaired_text)
            except Exception as inner_exc:
                last_exc = inner_exc
                prompt = (
                    "Still invalid JSON. Return one valid JSON object only.\n"
                    f"Required keys: {expected}\n"
                    f"Parse error: {str(inner_exc)[:500]}\n"
                    f"Raw model output:\n{repaired_text[:20000]}"
                )
        raise last_exc

    def _ensure_js_executable_contract(self, js_code: str) -> None:
        missing: list[str] = []
        if not re.search(r"\bfunction\s+createSlide\s*\(", js_code):
            missing.append("createSlide")
        if "module.exports" not in js_code:
            missing.append("module.exports")
        if missing:
            raise ValueError(f"LLM_OUTPUT_NOT_EXECUTABLE: missing {', '.join(missing)}")
