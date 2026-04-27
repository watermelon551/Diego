from __future__ import annotations

from typing import Any


def build_repair_started_payload(
    *,
    repair_round: int,
    mode: str,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "round": repair_round,
        "mode": mode,
    }
    if reason:
        payload["reason"] = reason
    return payload


def build_repair_history_entry(
    *,
    repair_round: int,
    mode: str,
    qa_passed: bool,
    source: str = "latest_artifacts",
) -> dict[str, Any]:
    return {
        "round": repair_round,
        "mode": mode,
        "source": source,
        "qa_passed": qa_passed,
    }


def build_repair_round_completed_payload(
    *,
    repair_round: int,
    mode: str,
    qa_passed: bool,
    source: str = "latest_artifacts",
) -> dict[str, Any]:
    return {
        "round": repair_round,
        "mode": mode,
        "qa_passed": qa_passed,
        "source": source,
    }


def increment_verification_cycles(qa_report: dict[str, Any]) -> None:
    cycles = int(qa_report.get("verification_cycles", 0))
    qa_report["verification_cycles"] = cycles + 1
