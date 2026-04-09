from __future__ import annotations

import asyncio
import json
from pathlib import Path

from service.models import (
    ConfirmOutlineRequest,
    GenerationMode,
    OutlineDocument,
    PromptRunRequest,
    RunStatus,
)
from service.orchestrator import build_orchestrator


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if raw:
        return raw
    return default or ""


def _ask_int(prompt: str, default: int, min_value: int, max_value: int) -> int:
    while True:
        raw = _ask(prompt, str(default))
        try:
            value = int(raw)
        except ValueError:
            print(f"请输入整数，范围 {min_value}-{max_value}")
            continue
        if value < min_value or value > max_value:
            print(f"超出范围，请输入 {min_value}-{max_value}")
            continue
        return value


def _print_outline(outline: OutlineDocument) -> None:
    print("\n===== 大纲预览 =====")
    print(f"版本: {outline.version}")
    print(f"摘要: {outline.summary}")
    for idx, node in enumerate(outline.nodes, start=1):
        print(f"\n[{idx:02d}] {node.title}")
        print(f"  page_type: {node.page_type.value} | layout: {node.layout_hint or '-'}")
        for b_idx, bullet in enumerate(node.bullets, start=1):
            print(f"  - ({b_idx}) {bullet}")
    print("===== 大纲结束 =====\n")


def _edit_outline_interactive(outline: OutlineDocument) -> OutlineDocument:
    edited = outline.model_copy(deep=True)
    total = len(edited.nodes)
    print("输入要编辑的页码（1-based），直接回车表示结束编辑。")
    while True:
        raw_idx = _ask("页码", "")
        if not raw_idx:
            break
        try:
            idx = int(raw_idx)
        except ValueError:
            print("页码必须是数字。")
            continue
        if idx < 1 or idx > total:
            print(f"页码越界，范围 1-{total}")
            continue
        node = edited.nodes[idx - 1]
        new_title = _ask("新标题（留空不改）", "")
        if new_title:
            node.title = new_title
        new_bullets_raw = _ask("新要点（用 | 分隔，留空不改）", "")
        if new_bullets_raw:
            node.bullets = [item.strip() for item in new_bullets_raw.split("|") if item.strip()]
        new_layout = _ask("新layout_hint（留空不改）", "")
        if new_layout:
            node.layout_hint = new_layout
        print(f"已更新第 {idx} 页。")
    return edited


async def _wait_for_status(
    orchestrator,
    run_id: str,
    expected: set[RunStatus],
    *,
    start_seq: int = 0,
    show_outline_tokens: bool = True,
) -> tuple[RunStatus, object, int]:
    last_status: RunStatus | None = None
    last_seq = max(0, start_seq)
    token_buffer = []
    while True:
        detail = await orchestrator.get_run_detail(run_id)
        if detail is None:
            raise RuntimeError(f"run 不存在: {run_id}")
        if detail.status != last_status:
            print(f"[状态] {detail.status.value}")
            last_status = detail.status
        for event in detail.events:
            if event.seq <= last_seq:
                continue
            last_seq = event.seq
            if event.event.value == "outline.token" and show_outline_tokens:
                token = str(event.payload.get("token", ""))
                token_buffer.append(token)
                if len(token_buffer) >= 20:
                    print("[大纲流式] " + "".join(token_buffer).strip())
                    token_buffer = []
            elif event.event.value in {
                "outline.completed",
                "slide.generated",
                "compile.completed",
                "run.failed",
                "slot.mapping.completed",
                "slide.preview.qa",
                "chart.truth.checked",
                "repair.round.completed",
            }:
                payload = json.dumps(event.payload, ensure_ascii=False)
                print(f"[事件] {event.event.value} {payload}")
        if detail.status in expected:
            if token_buffer:
                print("[大纲流式] " + "".join(token_buffer).strip())
            return detail.status, detail, last_seq
        await asyncio.sleep(0.5)


async def _prepare_template(orchestrator) -> str:
    while True:
        raw = _ask("请输入模板 pptx 路径", "")
        if not raw:
            print("模板模式必须提供模板路径。")
            continue
        path = Path(raw).expanduser().resolve()
        if not path.exists() or not path.is_file():
            print(f"文件不存在: {path}")
            continue
        if path.suffix.lower() != ".pptx":
            print("仅支持 .pptx")
            continue
        content = path.read_bytes()
        uploaded = await orchestrator.upload_template(filename=path.name, content=content)
        print(f"模板上传成功，template_id={uploaded.template_id}")
        return uploaded.template_id


async def main() -> None:
    base_dir = Path.cwd() / ".runtime"
    base_dir.mkdir(parents=True, exist_ok=True)
    try:
        orchestrator = build_orchestrator(base_dir)
    except Exception as exc:
        print(f"初始化失败: {exc}")
        print("建议先检查 .env；本地联调可配置 ASSET_PROVIDER=mock。")
        return

    print("ppt-agent-service 终端交互模式")
    print("直接回车可退出。")

    while True:
        prompt = _ask("\n请输入提示词", "")
        if not prompt:
            print("已退出。")
            return
        project_id = _ask("project_id", "default-project")
        target_slide_count = _ask_int("目标页数", 8, 1, 50)
        template_style = _ask("template_style", "default")
        mode_raw = _ask("generation_mode (scratch/template)", "scratch").lower()
        generation_mode = GenerationMode.TEMPLATE if mode_raw == "template" else GenerationMode.SCRATCH
        rag_raw = _ask("rag_source_ids（用 | 分隔，留空可不填）", "")
        rag_source_ids = [item.strip() for item in rag_raw.split("|") if item.strip()] if rag_raw else []

        template_id: str | None = None
        if generation_mode == GenerationMode.TEMPLATE:
            template_id = await _prepare_template(orchestrator)

        req = PromptRunRequest(
            prompt=prompt,
            project_id=project_id,
            rag_source_ids=rag_source_ids,
            template_style=template_style,
            target_slide_count=target_slide_count,
            generation_mode=generation_mode,
            template_id=template_id,
        )
        summary = await orchestrator.create_run(req.to_create_run_request())
        run_id = summary.run_id
        print(f"\nrun_id={run_id}")
        print(f"trace_id={summary.trace_id}")

        last_seq = 0
        status, detail, last_seq = await _wait_for_status(
            orchestrator,
            run_id,
            {RunStatus.AWAITING_OUTLINE_CONFIRM, RunStatus.FAILED},
            start_seq=last_seq,
            show_outline_tokens=True,
        )
        if status == RunStatus.FAILED:
            print(f"运行失败: error_code={detail.error_code}, stage={detail.failed_stage}")
            continue
        if detail.outline is None:
            print("未获取到大纲，终止本次运行。")
            continue

        _print_outline(detail.outline)
        outline_action = _ask("确认大纲？(y=确认, e=编辑后确认, n=不确认)", "y").lower()
        if outline_action == "n":
            print("本次运行保持在等待确认状态，可稍后通过 API 继续。")
            continue

        if outline_action == "e":
            edited_outline = _edit_outline_interactive(detail.outline)
            confirm_req = ConfirmOutlineRequest(
                approved=True,
                outline=edited_outline,
                base_version=detail.outline.version,
                change_reason="cli_edit",
            )
        else:
            confirm_req = ConfirmOutlineRequest(approved=True)

        await orchestrator.confirm_outline(run_id, confirm_req)

        status, final_detail, last_seq = await _wait_for_status(
            orchestrator,
            run_id,
            {RunStatus.SUCCEEDED, RunStatus.FAILED},
            start_seq=last_seq,
            show_outline_tokens=False,
        )
        if status == RunStatus.FAILED:
            print(f"\n运行失败: error_code={final_detail.error_code}, stage={final_detail.failed_stage}, retryable={final_detail.retryable}")
            if final_detail.template_mapping_report:
                print("template_mapping_report:")
                print(json.dumps(final_detail.template_mapping_report, ensure_ascii=False, indent=2))
            continue

        print("\n运行成功。")
        print(f"pptx_path: {final_detail.pptx_path}")
        print(f"compile_js_path: {final_detail.compile_js_path}")
        if final_detail.slides:
            print("slide js:")
            for item in final_detail.slides:
                print(f"  - slide-{item.slide_no:02d}: {item.js_path}")
        if final_detail.chart_truth_report:
            print("chart_truth_report:")
            print(json.dumps(final_detail.chart_truth_report, ensure_ascii=False, indent=2))
        if final_detail.qa_report:
            print("qa_report:")
            print(json.dumps(final_detail.qa_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
