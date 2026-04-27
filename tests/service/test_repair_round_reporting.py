from __future__ import annotations

from service.run.repair_round_reporting import (
    build_repair_history_entry,
    build_repair_round_completed_payload,
    build_repair_started_payload,
    increment_verification_cycles,
)


def test_repair_round_reporting_payloads_should_stay_deterministic() -> None:
    assert build_repair_started_payload(
        repair_round=0,
        mode="scratch",
        reason="mandatory_verify_cycle",
    ) == {
        "round": 0,
        "mode": "scratch",
        "reason": "mandatory_verify_cycle",
    }
    assert build_repair_started_payload(
        repair_round=2,
        mode="template",
    ) == {
        "round": 2,
        "mode": "template",
    }
    assert build_repair_history_entry(
        repair_round=1,
        mode="scratch",
        qa_passed=True,
    ) == {
        "round": 1,
        "mode": "scratch",
        "source": "latest_artifacts",
        "qa_passed": True,
    }
    assert build_repair_round_completed_payload(
        repair_round=1,
        mode="scratch",
        qa_passed=False,
    ) == {
        "round": 1,
        "mode": "scratch",
        "qa_passed": False,
        "source": "latest_artifacts",
    }


def test_increment_verification_cycles_should_update_in_place() -> None:
    qa_report = {"verification_cycles": 2}
    increment_verification_cycles(qa_report)
    assert qa_report["verification_cycles"] == 3
