from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from ...models import GenerationMode


def persist_failed_candidate_js(
    *,
    slides_dir: Path,
    slide_no: int,
    js_code: str,
    round_no: int,
    issues: list[str],
) -> None:
    failed_dir = slides_dir / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)
    failed_js = failed_dir / f"slide-{slide_no:02d}-last.js"
    failed_meta = failed_dir / f"slide-{slide_no:02d}-last.meta.json"
    failed_js.write_text(js_code, encoding="utf-8")
    failed_meta.write_text(
        json.dumps({"slide_no": slide_no, "round": round_no, "issues": issues[:20]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def split_qa_issues_by_slide(issues: list[str], *, dedupe_preserve_order) -> tuple[dict[int, list[str]], list[str]]:
    per_slide: dict[int, list[str]] = {}
    global_issues: list[str] = []
    for item in issues:
        text = str(item or "").strip()
        if not text:
            continue
        match = re.match(r"slide-(\d{2})(?:-[^:]+)?\.js:\s*(.+)", text, flags=re.IGNORECASE)
        if not match:
            global_issues.append(text)
            continue
        slide_no = int(match.group(1))
        reason = (match.group(2) or "").strip() or text
        bucket = per_slide.setdefault(slide_no, [])
        bucket.append(reason)
    return {k: dedupe_preserve_order(v) for k, v in per_slide.items()}, dedupe_preserve_order(global_issues)


async def persist_qa_failure_artifacts(
    *,
    store: Any,
    run_id: str,
    mode: GenerationMode,
    dedupe_preserve_order,
) -> dict[str, Any]:
    run = await store.get_run(run_id)
    if run is None:
        return {}
    qa_report = run.qa_report if isinstance(run.qa_report, dict) else {}
    issues = [str(item) for item in qa_report.get("issues", []) if str(item).strip()] if isinstance(qa_report.get("issues", []), list) else []
    issues_by_slide, global_issues = split_qa_issues_by_slide(issues, dedupe_preserve_order=dedupe_preserve_order)

    artifact_dir = Path(run.artifact_dir)
    report_path = artifact_dir / "qa_failed_issues.json"
    payload = {
        "run_id": run_id,
        "mode": mode.value,
        "issue_count": len(issues),
        "issues": issues[:200],
        "issues_by_slide": {str(k): v for k, v in sorted(issues_by_slide.items(), key=lambda x: x[0])},
        "global_issues": global_issues[:80],
        "qa_blocking_rules": [
            {"slide_no": slide_no, "rule_name": reasons[0] if reasons else "", "source_stage": "final_qa"}
            for slide_no, reasons in sorted(issues_by_slide.items(), key=lambda x: x[0]) if reasons
        ][:80],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    copied: list[str] = []
    if mode == GenerationMode.SCRATCH:
        slides_dir = artifact_dir / "slides"
        failed_dir = slides_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        for slide_no, reasons in sorted(issues_by_slide.items(), key=lambda x: x[0]):
            src = slides_dir / f"slide-{slide_no:02d}.js"
            if not src.exists():
                continue
            dst = failed_dir / f"slide-{slide_no:02d}-last.js"
            meta = failed_dir / f"slide-{slide_no:02d}-last.meta.json"
            shutil.copy2(src, dst)
            meta.write_text(
                json.dumps(
                    {"slide_no": slide_no, "round": None, "issues": reasons[:40], "source": "final_qa"},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            copied.append(str(dst))

    return {
        "qa_failed_report": str(report_path),
        "qa_issue_count": len(issues),
        "qa_blocking_rule_count": len(payload["qa_blocking_rules"]),
        "qa_blocking_rules": payload["qa_blocking_rules"],
        "failed_slide_js": copied,
    }
