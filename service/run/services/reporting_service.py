from __future__ import annotations

from typing import Any

from ...models import RunRecord


class ReportingService:
    def __init__(self, orchestrator: Any) -> None:
        self.orch = orchestrator

    async def append_chart_truth_report(self, *, run_id: str, entry: dict[str, Any]) -> None:
        orch = self.orch

        def apply(r: RunRecord) -> None:
            report = dict(r.chart_truth_report) if isinstance(r.chart_truth_report, dict) else {}
            slides = list(report.get("slides", []))
            slides = [item for item in slides if int(item.get("slide_no", -1)) != int(entry.get("slide_no", -1))]
            slides.append(entry)
            slides.sort(key=lambda item: int(item.get("slide_no", 0)))
            report["slides"] = slides
            report["passed"] = all(bool(item.get("has_verified_data", False)) for item in slides)
            r.chart_truth_report = report

        await orch.store.update_run(run_id, apply)

    async def append_quality_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        orch = self.orch

        def apply(r: RunRecord) -> None:
            report = dict(r.quality_report) if isinstance(r.quality_report, dict) else {}
            slides = list(report.get("slides", []))
            slides = [item for item in slides if int(item.get("slide_no", -1)) != int(entry.get("slide_no", -1))]
            slides.append(entry)
            slides.sort(key=lambda item: int(item.get("slide_no", 0)))
            report["slides"] = slides
            report["engine"] = orch.settings.generation_engine
            report["passed"] = all(int(item.get("passed_round", 0)) > 0 for item in slides)
            r.quality_report = report

        await orch.store.update_run(run_id, apply)

    async def append_quality_gate_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        orch = self.orch

        def apply(r: RunRecord) -> None:
            report = dict(r.quality_gate_report) if isinstance(r.quality_gate_report, dict) else {}
            rounds = list(report.get("rounds", []))
            rounds.append(entry)
            report["rounds"] = rounds
            threshold = int(entry.get("threshold", 80))
            report["threshold"] = threshold
            latest_by_slide: dict[int, dict[str, Any]] = {}
            for item in rounds:
                slide_no = int(item.get("slide_no", 0))
                prev = latest_by_slide.get(slide_no)
                if prev is None or int(item.get("round", 0)) >= int(prev.get("round", 0)):
                    latest_by_slide[slide_no] = item
            report["passed"] = bool(latest_by_slide) and all(bool(item.get("passed", False)) for item in latest_by_slide.values())
            r.quality_gate_report = report

        await orch.store.update_run(run_id, apply)

    async def append_candidate_selection_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        orch = self.orch

        def apply(r: RunRecord) -> None:
            report = dict(r.candidate_selection_report) if isinstance(r.candidate_selection_report, dict) else {}
            rounds = list(report.get("rounds", []))
            rounds.append(entry)
            report["rounds"] = rounds
            by_slide: dict[int, dict[str, Any]] = {}
            for item in rounds:
                slide_no = int(item.get("slide_no", 0))
                prev = by_slide.get(slide_no)
                if prev is None or int(item.get("round", 0)) >= int(prev.get("round", 0)):
                    by_slide[slide_no] = item
            report["final_by_slide"] = [by_slide[key] for key in sorted(by_slide)]
            r.candidate_selection_report = report

        await orch.store.update_run(run_id, apply)

    async def append_artifact_cleanup_entry(self, *, run_id: str, entry: dict[str, Any]) -> None:
        orch = self.orch

        def apply(r: RunRecord) -> None:
            report = dict(r.artifact_cleanup_report) if isinstance(r.artifact_cleanup_report, dict) else {}
            items = list(report.get("items", []))
            items.append(entry)
            report["items"] = items
            report["deleted_count"] = sum(1 for item in items if item.get("action") == "deleted")
            report["kept_count"] = sum(1 for item in items if item.get("action") == "kept_by_debug")
            r.artifact_cleanup_report = report

        await orch.store.update_run(run_id, apply)

    async def append_repair_history(self, *, run_id: str, entry: dict[str, Any]) -> None:
        orch = self.orch

        def apply(r: RunRecord) -> None:
            history = list(r.repair_history)
            history.append(entry)
            r.repair_history = history

        await orch.store.update_run(run_id, apply)
