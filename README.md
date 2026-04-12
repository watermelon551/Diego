# ppt-agent-service

`ppt-agent-service` 是一个与上游业务系统解耦的 PPT 生成微服务，负责把主题与资料范围转为可追溯的课件产物。

## 项目目标摘要

- 提供完整闭环：`RAG检索 -> 大纲流式 -> 大纲确认 -> 逐页 JS 生成 -> 编译 -> PPTX 产物返回`。
- 标准输入：`topic/project_id/rag_source_ids/template_style/target_slide_count`。
- 标准输出：`OutlineDocument`、逐页 `slide-xx.js`、最终 `pptx`、`citation_map`。
- 提供可消费事件流，至少覆盖：`outline.token`、`outline.completed`、`slide.generated`、`compile.completed`、`run.failed`。
- 全链路可观测：每次运行记录 `run_id`、`trace_id`、阶段耗时与错误码。

完整规范见：[PROJECT_GOALS.md](./docs/PROJECT_GOALS.md)

## 项目结构（重构后）

- `service/api`: HTTP 路由与请求入口
- `service/run`: 运行编排与状态机（`RunOrchestrator`）
  - `service/run/flows`: outline/scratch/template 三条主流程服务
  - `service/run/services`: quality/compile/reporting 领域服务（编排逻辑下沉）
- `service/llm`: LLM 协议、OpenAI-compatible 客户端、mock 与解析工具
- `service/slides`: scratch 生成侧 JS 质量门禁与诊断 mixin
- `service/templates`: template 编辑、槽位映射、图表与布局重排 mixin
- `service/design`: 设计策略（style profile + style catalog）
- `service/infra`: 基础设施（`RunStore`）
- `service/models`: 契约模型（请求/响应/运行态）

兼容性说明：
- 旧导入路径仍可用（例如 `service.orchestrator` / `service.llm_client`），当前通过 shim re-export 兼容，后续版本再清理。
- 若要在本地显式看到旧路径弃用提示，可设置 `PPT_AGENT_SHIM_WARNINGS=1`。

## 快速开始

```powershell
# 1) 创建虚拟环境
D:\program\Anaconda\python.exe -m venv .venv

# 2) 安装依赖
.\.venv\Scripts\python.exe -m pip install -e .[dev]
npm install

# 3) 配置大模型（必须）
Copy-Item .env.example .env
# 然后编辑 .env 中的 LLM_API_STYLE / LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
# 生成引擎默认 `GENERATION_ENGINE=agentic_v2`
# 本地默认 `ASSET_PROVIDER=mock`，无需图片 API key；要接入真实图片源可改为 `auto/unsplash/pexels`

# 4) 启动服务
.\.venv\Scripts\python.exe .\scripts\run_dev.py
```

服务默认地址：`http://127.0.0.1:8000`

> 当前版本支持 `openai_chat` 和 `anthropic_messages` 两种协议（由 `LLM_API_STYLE` 控制），未配置 `.env` 必填项时会直接报错。
> `agentic_v2` 会逐页进行 `codegen -> preview QA -> critic repair` 多轮闭环，默认自动清理临时 `slide-XX-preview.pptx`（可用 `DEBUG_KEEP_PREVIEWS=1` 保留）。

## 终端交互调试（推荐）

如果你希望直接在终端里“输入提示词 -> 看大纲 -> 确认 -> 看产物路径”，可使用：

```powershell
.\.venv\Scripts\python.exe .\scripts\run_cli.py
```

交互脚本能力：
- 终端输入 `prompt/project_id/页数/style/mode`；
- 模板模式可直接输入本地 `.pptx` 路径并自动上传；
- 自动打印大纲，支持“直接确认”或“编辑后确认”；
- 生成完成后输出 `pptx_path`、`compile_js_path`、每页 `slide-xx.js` 路径；
- 同步输出关键事件与 QA/图表真实性报告，便于调试。

## API 工作流

### Scratch 生成（严格 skill 流程）
1. `POST /v1/ppt/runs` 或 `POST /v1/ppt/runs/prompt` 创建 run（进入 `OUTLINE_DRAFTING`）
2. `GET /v1/ppt/runs/{run_id}/events` 订阅 SSE 事件流
3. `GET /v1/ppt/runs/{run_id}` 查询状态（等待 `AWAITING_OUTLINE_CONFIRM`）
4. `POST /v1/ppt/runs/{run_id}/outline/confirm`
   - `approved=false`：仅更新大纲，保持 `AWAITING_OUTLINE_CONFIRM`
   - `approved=true`：确认并进入生成
5. `GET /v1/ppt/runs/{run_id}` 获取最终产物路径（`compile.js`、`output.pptx`）

运行结果中会返回：
- `slides[].js_path`：每页生成的 `slide-xx.js` 文件路径
- `pptx_path`：最终编译产物 `presentation.pptx` 路径

### Template 编辑模式
1. `POST /v1/ppt/templates` 上传 `template.pptx`，获得 `template_id`
2. `POST /v1/ppt/runs` 时带 `generation_mode=template` 与 `template_id`
3. 按同样的 run + SSE + confirm 流程执行，产出 `edited.pptx` + `template_slides/slide-xx.js` + `template_slides/compile.js`

`POST /v1/ppt/runs` 请求新增可选字段：
- `generation_mode`: `scratch | template`（默认 `scratch`）
- `template_id`: 当 `generation_mode=template` 时必填
- `visual_policy`: `auto | media_required | basic_graphics_only`（默认 `auto`，仅对 scratch 质量门禁生效）

Template 模式返回：
- `slides[].js_path`：模板流程生成的逐页 `slide-xx.js`
- `compile_js_path`：模板流程 `template_slides/compile.js`
- `pptx_path`：模板编辑打包后的 `edited.pptx`

`POST /v1/ppt/runs/prompt` 请求字段：
- `prompt`: 用户提示词（作为主题输入）
- `visual_policy`: 与 `POST /v1/ppt/runs` 一致
- 其余字段与 `POST /v1/ppt/runs` 保持一致

## 运行测试

```powershell
New-Item -ItemType Directory -Force -Path .runtime,.runtime\pytest_tmp,.runtime\pytest_cache | Out-Null
$env:TEMP=(Resolve-Path '.runtime').Path
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime\pytest_tmp -o cache_dir=.runtime\pytest_cache
```

测试已按主题拆分：
- `tests/integration/`: 端到端流程与 API/SSE
- `tests/service/`: service 内部行为与质量门禁
- `tests/support/`: 共享 mock / fixture / helper

## Skill 对齐能力

- 按 skill 执行多轮大模型调用：全局规划+评审、逐页生成+审查。
- 产物结构：`slides/slide-xx.js`、`slides/compile.js`、`slides/output/presentation.pptx`。
- 编译方式：`node slides/compile.js`（PptxGenJS）。
- QA：逐页 preview QA + markitdown 检查 + 规则校验（page badge、主题键、导出契约等），失败自动 repair 重试。

## 文档目录

- [项目目标基线](./docs/PROJECT_GOALS.md)
- [架构与契约](./docs/ARCHITECTURE.md)
- [未来对接改动点（仅计划）](./docs/SPECTRA_CHANGE_POINTS.md)

## 当前阶段边界

- 当前阶段只建设本项目文档与新服务自身实现。
- 当前阶段不修改任何外部系统代码。
