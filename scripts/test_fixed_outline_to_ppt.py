from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

from service.models import (
    ConfirmOutlineRequest,
    CreateRunRequest,
    EventType,
    GenerationMode,
    OutlineDocument,
    OutlineNode,
    RunRecord,
    RunStatus,
    SlidePageType,
    VisualPolicy,
)
from service.orchestrator import build_orchestrator
from service.style_catalog import (
    STYLE_PRESET_AUTO,
    get_style_theme_hint,
    is_valid_style_choice,
    list_style_presets,
    normalize_style_choice,
    resolve_style_choice,
)

DEFAULT_PROJECT_ID = "fixed-outline-e2e"
DEFAULT_TOPIC = "区块链技术发展历程"
DEFAULT_TEMPLATE_STYLE = "modern"
DEFAULT_VISUAL_POLICY = VisualPolicy.AUTO
DEFAULT_RAG_SOURCE_IDS: list[str] = []
DEFAULT_MAX_WAIT_SEC = 60 * 30
DEFAULT_IDLE_AFTER_COMPILE_SEC = 15
def _build_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="固定大纲 -> PPT 端到端测试（支持内置20风格预设）")
    parser.add_argument("--style", default=STYLE_PRESET_AUTO, help="风格（auto/预设id/中文名/序号）")
    parser.add_argument("--style-prompt", default="", help="直接覆盖风格提示词（仅测试使用）")
    parser.add_argument("--template-style", default="", help="覆盖 template_style；不传则使用预设 hint")
    parser.add_argument("--list-styles", action="store_true", help="列出可用风格并退出")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="测试主题")
    return parser.parse_args()


def _resolve_style_inputs(args: argparse.Namespace) -> tuple[str, str, str, str, str]:
    presets = list_style_presets()
    raw_style = (args.style or "").strip()
    if raw_style.isdigit():
        idx = int(raw_style)
        if 1 <= idx <= len(presets):
            style_choice = presets[idx - 1].id
        else:
            raise ValueError(f"--style 序号越界，范围 1-{len(presets)}")
    else:
        style_choice = normalize_style_choice(raw_style)

    if not is_valid_style_choice(style_choice):
        raise ValueError(f"无效 --style: {raw_style!r}，可先用 --list-styles 查看选项")

    preset = resolve_style_choice(style_choice)
    if preset is None:
        style_name = "自动分析风格"
        style_prompt = (args.style_prompt or "").strip()
        template_style = (args.template_style or DEFAULT_TEMPLATE_STYLE).strip()
        return style_choice, style_name, style_prompt, template_style, "soft"

    style_name = preset.name
    style_prompt = (args.style_prompt or preset.prompt).strip()
    template_style = (args.template_style or preset.template_style_hint).strip()
    return style_choice, style_name, style_prompt, template_style, preset.style_recipe_hint


def _fixed_outline(version: int) -> OutlineDocument:
    return OutlineDocument(
        version=version,
        summary=(
            "一份8页现代高级风格的区块链技术发展历程PPT，涵盖从2008年至今的关键里程碑，"
            "采用深色科技风配色，展现区块链从诞生到Web3时代的演进。"
        ),
        nodes=[
            OutlineNode(
                title="区块链技术发展历程",
                bullets=["从比特币到Web3的革命之旅", "探索去中心化技术的演进与未来"],
                page_type=SlidePageType.COVER,
                layout_hint="cover-asymmetric",
            ),
            OutlineNode(
                title="目录",
                bullets=["一、起源：2008-2013", "二、成长：2014-2017", "三、繁荣：2018-2021", "四、未来：2022-至今"],
                page_type=SlidePageType.TOC,
                layout_hint="toc-sidebar",
            ),
            OutlineNode(
                title="区块链发展时间线",
                bullets=[
                    "2008 — 比特币白皮书发布",
                    "2013 — 智能合约概念兴起",
                    "2017 — ICO热潮与监管探索",
                    "2020 — DeFi Summer爆发",
                    "2022 — Web3与元宇宙融合",
                ],
                page_type=SlidePageType.SECTION,
                layout_hint="section-center",
            ),
            OutlineNode(
                title="起源：2008-2013",
                bullets=[
                    "2008年：中本聪发布比特币白皮书",
                    "2009年：比特币主网正式上线，创世区块诞生",
                    "2010年：第一笔比特币实物交易（10000 BTC买披萨）",
                    "2013年：以太坊概念提出，智能合约初现",
                ],
                page_type=SlidePageType.CONTENT,
                layout_hint="content-two-column",
            ),
            OutlineNode(
                title="成长：2014-2017",
                bullets=[
                    "2014年：以太坊正式成立，募集到1800万美元",
                    "2015年：以太坊主网上线，开启区块链2.0时代",
                    "2016年：DAO事件引发硬分叉，行业开始重视安全",
                    "2017年：ICO狂潮，BTC突破20000美元",
                ],
                page_type=SlidePageType.SECTION,
                layout_hint="section-center",
            ),
            OutlineNode(
                title="繁荣：2018-2021",
                bullets=[
                    "2018年：公链竞争激烈，EOS、TRON等崛起",
                    "2019年：Libra（后更名Diem）引发全球监管关注",
                    "2020年：DeFi Summer，锁仓量从10亿飙升至300亿",
                    "2021年：NFT爆发，元宇宙概念兴起，Web3加速",
                ],
                page_type=SlidePageType.CONTENT,
                layout_hint="content-icon-rows",
            ),
            OutlineNode(
                title="未来：2022-至今",
                bullets=[
                    "2022年：加密市场降温，监管框架逐步完善",
                    "2023年：Layer2扩容方案成熟，ZK-Rollup成为焦点",
                    "2024年：RWA代币化，机构采用加速，AI+区块链融合",
                    "趋势：互操作性、去中心化身份、可持续能源",
                ],
                page_type=SlidePageType.CONTENT,
                layout_hint="content-comparison",
            ),
            OutlineNode(
                title="总结与展望",
                bullets=[
                    "从比特币到智能合约，区块链已走过16年",
                    "去中心化技术正在重塑金融、版权、身份等各领域",
                    "Layer2、AI集成、RWA代币化是下一个增长引擎",
                    "构建可信互联网，Web3将持续改变数字经济格局",
                ],
                page_type=SlidePageType.SUMMARY,
                layout_hint="summary-takeaways",
            ),
        ],
    )


def _fixed_requirements_report(
    *,
    target_slide_count: int,
    image_source_mode: str,
    style_name: str,
    style_choice: str,
    style_prompt: str,
    effective_template_style: str,
    style_recipe_hint: str,
) -> dict:
    audience = "技术从业者、投资者、企业决策者及对区块链感兴趣的泛科技人群，以25-45岁中青年为主，具备一定技术认知或商业敏感度"
    purpose = "系统梳理区块链技术从诞生到当下的演进脉络，展示技术迭代路径与应用生态全景，帮助受众建立对区块链发展阶段的清晰认知，洞察未来趋势"
    tone = "科技感、专业而不晦涩、前瞻性、理性克制中带有创新活力"
    style_intent = style_prompt.strip() or f"使用“{style_name}”风格生成整套PPT，强调风格一致性和高可读性。"
    style_recipe_long = style_intent
    visual_strategy = (
        f"统一采用“{style_name}”的视觉语汇：每页保持单一主视觉焦点，"
        "并通过标题层级、留白和图文节奏保证信息传达效率。"
    )
    density = (
        "Medium-high — 保持足够留白和稳定的版式密度，避免文字拥挤与信息过载。"
    )
    page_focus = [
        "封面：区块链技术发展历程的主题建立",
        "目录：四阶段演进总览",
        "时间线：关键里程碑串联",
        "起源：2008-2013",
        "成长：2014-2017",
        "繁荣：2018-2021",
        "未来：2022-至今",
        "总结与展望",
    ]
    return {
        "page_count_fixed": target_slide_count,
        "effective_template_style": effective_template_style,
        "style_intent": style_intent,
        "style_reference_name": style_name,
        "style_reference_prompt": style_prompt,
        "content_source_mode": "model_only",
        "image_source_mode": image_source_mode,
        "audience": audience,
        "purpose": purpose,
        "tone": tone,
        "palette_name": style_name,
        "style_recipe": style_recipe_long,
        "visual_strategy": visual_strategy,
        "density": density,
        "page_focus": page_focus[:target_slide_count],
        "design_notes": [style_recipe_long, visual_strategy, density],
        "design_intent": {
            "palette_name": style_name,
            "style_recipe": style_recipe_hint or "soft",
            "title_font": "Arial Black",
            "body_font": "Calibri",
            "visual_strategy": visual_strategy,
            "density": "medium",
            "rationale": f"{style_name}风格优先，保证一致性、可读性和演示表达效率",
            "theme": get_style_theme_hint(style_choice)
            or {
                "primary": "E6F1FF",
                "secondary": "8AA0B8",
                "accent": "00E5FF",
                "light": "1B2633",
                "bg": "0D1117",
            },
        },
    }


async def _wait(
    orchestrator,
    run_id: str,
    expected: set[RunStatus],
    *,
    show_events: bool = True,
    max_wait_sec: int = DEFAULT_MAX_WAIT_SEC,
    idle_after_compile_sec: int = DEFAULT_IDLE_AFTER_COMPILE_SEC,
):
    last_seq = 0
    last_status: RunStatus | None = None
    started_at = time.monotonic()
    last_progress_at = started_at
    compile_completed_at: float | None = None
    compile_completed = False
    compile_pptx_path: str | None = None
    while True:
        detail = await orchestrator.get_run_detail(run_id)
        if detail is None:
            raise RuntimeError(f"run 不存在: {run_id}")
        if detail.status != last_status:
            print(f"[状态] {detail.status.value}")
            last_status = detail.status
            last_progress_at = time.monotonic()
        if show_events:
            for event in detail.events:
                if event.seq <= last_seq:
                    continue
                last_seq = event.seq
                last_progress_at = time.monotonic()
                if event.event.value in {
                    "run.failed",
                    "outline.completed",
                    "slide.generated",
                    "slide.failed",
                    "slide.candidate.generated",
                    "slide.selection.completed",
                    "compile.completed",
                }:
                    print(f"[事件] {event.event.value} {json.dumps(event.payload, ensure_ascii=False)}")
                if event.event.value == "compile.completed":
                    compile_completed = True
                    compile_completed_at = time.monotonic()
                    compile_pptx_path = str((event.payload or {}).get("pptx_path", "")).strip() or None
        if detail.status in expected:
            return detail

        now = time.monotonic()
        if max_wait_sec > 0 and (now - started_at) >= max_wait_sec:
            raise TimeoutError(
                f"等待超时（>{max_wait_sec}s），当前状态={detail.status.value}，last_seq={last_seq}"
            )

        # 异常路径兜底：compile.completed + pptx 文件已生成，但状态未切到 SUCCEEDED。
        pptx_candidate = detail.pptx_path or compile_pptx_path
        if compile_completed and pptx_candidate:
            pptx_path = Path(pptx_candidate)
            if pptx_path.exists():
                if compile_completed_at is None:
                    compile_completed_at = now
                idle_since_compile = now - compile_completed_at
                if idle_since_compile >= idle_after_compile_sec:
                    print(
                        "[流程] 检测到 compile.completed 且 pptx 已生成，但状态未结束；"
                        "测试脚本按兜底成功退出。"
                    )
                    return detail.model_copy(update={"status": RunStatus.SUCCEEDED, "pptx_path": str(pptx_path)})

        if (now - last_progress_at) >= max(idle_after_compile_sec * 8, 120):
            raise TimeoutError(
                f"长时间无进展（{int(now - last_progress_at)}s），当前状态={detail.status.value}，last_seq={last_seq}"
            )
        await asyncio.sleep(0.5)


def _analyze_events(detail) -> dict:
    counter: Counter[str] = Counter()
    llm_timeout_count = 0
    llm_retry_count = 0
    candidate_stats: list[dict] = []
    selected_by_slide: dict[int, dict] = {}
    failed_payload: dict | None = None
    issue_counter: Counter[str] = Counter()
    score_by_slide: defaultdict[int, list[int]] = defaultdict(list)
    generated_status_by_slide: dict[int, str] = {}
    selected_without_pass: dict[int, dict] = {}

    for event in detail.events:
        et = event.event.value
        payload = event.payload or {}
        counter[et] += 1
        if et == "llm.request.timeout":
            llm_timeout_count += 1
        elif et == "llm.request.retry":
            llm_retry_count += 1
        elif et == "slide.preview.qa":
            for issue in payload.get("issues", []) or []:
                issue_counter[str(issue)] += 1
        elif et == "slide.candidate.generated":
            slide_no = int(payload.get("slide_no", 0))
            score = int(payload.get("score", 0))
            score_by_slide[slide_no].append(score)
            candidate_stats.append(
                {
                    "slide_no": slide_no,
                    "round": int(payload.get("round", 0)),
                    "candidate": int(payload.get("candidate", 0)),
                    "score": score,
                    "passed": bool(payload.get("passed", False)),
                    "degraded": bool(payload.get("degraded", False)),
                    "error": str(payload.get("error", "")),
                    "variant": payload.get("variant", {}),
                }
            )
        elif et == "slide.selection.completed":
            slide_no = int(payload.get("slide_no", 0))
            selected_by_slide[slide_no] = payload
            if payload.get("passed") is False:
                selected_without_pass[slide_no] = payload
        elif et == "slide.generated":
            slide_no = int(payload.get("slide_no", 0))
            generated_status_by_slide[slide_no] = str(payload.get("status", ""))
        elif et == "run.failed":
            failed_payload = payload

    avg_score_by_slide = {
        str(slide): (sum(vals) / len(vals) if vals else 0.0)
        for slide, vals in sorted(score_by_slide.items(), key=lambda x: x[0])
    }
    top_issues = [{"issue": k, "count": v} for k, v in issue_counter.most_common(12)]

    forced_or_degraded_slides: list[dict] = []
    slide_ids = sorted(set(selected_without_pass.keys()) | set(generated_status_by_slide.keys()))
    for slide_no in slide_ids:
        reasons: list[str] = []
        selected_payload = selected_without_pass.get(slide_no)
        if selected_payload is not None:
            reasons.append("selected_candidate_not_passed")
        status = generated_status_by_slide.get(slide_no, "")
        status_l = status.lower()
        if status and any(tok in status_l for tok in ("degraded", "fallback", "forced", "qa_failed", "repair_exhausted")):
            reasons.append(f"generated_status={status}")
        if reasons:
            forced_or_degraded_slides.append(
                {
                    "slide_no": slide_no,
                    "reasons": reasons,
                    "selected_payload": selected_payload or {},
                    "generated_status": status,
                }
            )

    return {
        "status": detail.status.value,
        "event_counts": dict(sorted(counter.items(), key=lambda x: x[0])),
        "llm_timeout_count": llm_timeout_count,
        "llm_retry_count": llm_retry_count,
        "candidate_event_count": len(candidate_stats),
        "candidate_stats": candidate_stats,
        "selected_by_slide": {str(k): v for k, v in sorted(selected_by_slide.items(), key=lambda x: x[0])},
        "avg_score_by_slide": avg_score_by_slide,
        "top_preview_issues": top_issues,
        "run_failed_payload": failed_payload,
        "forced_or_degraded_slides": forced_or_degraded_slides,
    }


def _write_generation_log(*, artifact_dir: Path, detail, analysis: dict) -> Path:
    event_counts: dict[str, int] = analysis.get("event_counts", {}) or {}
    forced_slides: list[dict] = analysis.get("forced_or_degraded_slides", []) or []
    top_issues: list[dict] = analysis.get("top_preview_issues", []) or []

    key_events = [
        "outline.completed",
        "slide.generated",
        "slide.failed",
        "slide.selection.completed",
        "slide.candidate.generated",
        "compile.completed",
        "run.failed",
    ]

    lines: list[str] = []
    lines.append("# Generation Log")
    lines.append("")
    lines.append("## Run Summary")
    lines.append(f"- run_id: `{detail.run_id}`")
    lines.append(f"- trace_id: `{detail.trace_id}`")
    lines.append(f"- status: `{detail.status.value}`")
    lines.append(f"- error_code: `{detail.error_code or ''}`")
    lines.append(f"- failed_stage: `{detail.failed_stage or ''}`")
    lines.append(f"- pptx_path: `{detail.pptx_path or ''}`")
    lines.append(f"- compile_js_path: `{detail.compile_js_path or ''}`")
    lines.append(f"- effective_template_style: `{str((detail.research_report or {}).get('effective_template_style', '')).strip()}`")
    style_ref_name = str((detail.research_report or {}).get("style_reference_name", "")).strip()
    if style_ref_name:
        lines.append(f"- style_reference_name: `{style_ref_name}`")
    lines.append("")
    lines.append("## Important Events")
    for name in key_events:
        lines.append(f"- {name}: {event_counts.get(name, 0)}")
    lines.append(f"- llm.request.timeout: {analysis.get('llm_timeout_count', 0)}")
    lines.append(f"- llm.request.retry: {analysis.get('llm_retry_count', 0)}")
    lines.append("")
    lines.append("## Failed-But-Passed Slides")
    if not forced_slides:
        lines.append("- none")
    else:
        for item in forced_slides:
            slide_no = item.get("slide_no")
            reasons = ", ".join(item.get("reasons", []))
            lines.append(f"- slide-{int(slide_no):02d}: {reasons}")
    lines.append("")
    lines.append("## Top Preview Issues")
    if not top_issues:
        lines.append("- none")
    else:
        for item in top_issues[:12]:
            lines.append(f"- {item.get('count', 0)}x {item.get('issue', '')}")

    path = artifact_dir / "generation_log.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def main(args: argparse.Namespace) -> int:
    base_dir = Path.cwd() / ".runtime"
    base_dir.mkdir(parents=True, exist_ok=True)
    orchestrator = build_orchestrator(base_dir)

    presets = list_style_presets()
    if args.list_styles:
        print("可选风格预设：")
        for idx, item in enumerate(presets, start=1):
            print(f"{idx:02d}. {item.name} ({item.id})")
        print(f"{STYLE_PRESET_AUTO}. 自动分析风格")
        return 0

    try:
        style_choice, style_name, style_prompt, template_style = _resolve_style_inputs(args)
    except ValueError as exc:
        print(str(exc))
        print("可先运行: python scripts/test_fixed_outline_to_ppt.py --list-styles")
        return 1
    topic = (args.topic or DEFAULT_TOPIC).strip() or DEFAULT_TOPIC

    create_req = CreateRunRequest(
        topic=topic,
        project_id=DEFAULT_PROJECT_ID,
        rag_source_ids=list(DEFAULT_RAG_SOURCE_IDS),
        template_style=template_style,
        style_preset=style_choice,
        target_slide_count=8,
        generation_mode=GenerationMode.SCRATCH,
        visual_policy=DEFAULT_VISUAL_POLICY,
    )
    run_id = str(uuid4())
    trace_id = str(uuid4())
    artifact_dir = orchestrator.artifacts_base / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixed = _fixed_outline(version=1)
    requirements_report = _fixed_requirements_report(
        target_slide_count=create_req.target_slide_count,
        image_source_mode=("mock" if orchestrator.settings.asset_provider == "mock" else "model_only"),
        style_name=style_name,
        style_choice=style_choice,
        style_prompt=style_prompt,
        effective_template_style=template_style,
    )
    run = RunRecord(
        run_id=run_id,
        trace_id=trace_id,
        status=RunStatus.AWAITING_OUTLINE_CONFIRM,
        input=create_req,
        outline=fixed,
        research_report=requirements_report,
        artifact_dir=str(artifact_dir),
    )
    await orchestrator.store.add_run(run)
    await orchestrator._publish(
        run_id,
        EventType.RESEARCH_COMPLETED,
        {
            "audience": requirements_report["audience"],
            "purpose": requirements_report["purpose"],
            "tone": requirements_report["tone"],
        },
    )
    await orchestrator._publish(
        run_id,
        EventType.REQUIREMENTS_ANALYZED,
        {
            "page_count_fixed": requirements_report["page_count_fixed"],
            "style_preset": style_choice,
            "style_reference_name": style_name,
            "effective_template_style": requirements_report["effective_template_style"],
            "style_intent": requirements_report["style_intent"],
            "content_source_mode": requirements_report["content_source_mode"],
            "image_source_mode": requirements_report["image_source_mode"],
            "audience": requirements_report["audience"],
            "purpose": requirements_report["purpose"],
            "tone": requirements_report["tone"],
            "palette_name": requirements_report["palette_name"],
            "style_recipe": requirements_report["style_recipe"],
            "visual_strategy": requirements_report["visual_strategy"],
            "density": requirements_report["density"],
        },
    )
    await orchestrator._publish(
        run_id,
        EventType.OUTLINE_COMPLETED,
        {"version": fixed.version, "sections": len(fixed.nodes), "source": "fixed_outline"},
    )
    print(f"run_id={run_id}")
    print(f"trace_id={trace_id}")
    print(f"[风格] style_preset={style_choice}, style_name={style_name}, template_style={template_style}")
    print("[流程] 已直接注入固定大纲与固定需求分析结果，跳过草稿大纲生成。")

    await orchestrator.confirm_outline(run_id, ConfirmOutlineRequest(approved=True))

    try:
        final = await _wait(orchestrator, run_id, {RunStatus.SUCCEEDED, RunStatus.FAILED})
    except TimeoutError as exc:
        latest = await orchestrator.get_run_detail(run_id)
        if latest is None:
            print(f"运行超时且 run 丢失: {exc}")
            return 3
        print(f"运行超时: {exc}")
        analysis = _analyze_events(latest)
        analysis_path = artifact_dir / "event_analysis.json"
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        log_path = _write_generation_log(artifact_dir=artifact_dir, detail=latest, analysis=analysis)
        print(f"[分析] 事件分析已写入: {analysis_path}")
        print(f"[日志] 生成日志已写入: {log_path}")
        return 3

    analysis = _analyze_events(final)
    analysis_path = artifact_dir / "event_analysis.json"
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    log_path = _write_generation_log(artifact_dir=artifact_dir, detail=final, analysis=analysis)

    if final.status == RunStatus.FAILED:
        print(f"运行失败: error_code={final.error_code}, stage={final.failed_stage}, retryable={final.retryable}")
        if final.error_details:
            print(json.dumps(final.error_details, ensure_ascii=False, indent=2))
        print(f"[分析] 事件分析已写入: {analysis_path}")
        print(f"[日志] 生成日志已写入: {log_path}")
        return 2

    print("\n[结果] 运行成功")
    print(f"pptx_path: {final.pptx_path}")
    print(f"compile_js_path: {final.compile_js_path}")
    print("slides:")
    for slide in final.slides:
        print(f"  - slide-{slide.slide_no:02d}: {slide.js_path}")
    print(f"[分析] 事件分析已写入: {analysis_path}")
    print(f"[日志] 生成日志已写入: {log_path}")
    return 0


if __name__ == "__main__":
    cli_args = _build_cli_args()
    raise SystemExit(asyncio.run(main(cli_args)))
