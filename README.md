# Diego

`Diego` 是一个独立的 PPT 生成微服务，提供统一的“主题到生成结果”能力。当前版本已支持 `scratch`（自由生成）与 `template`（模板编辑）两条主链路，并具备状态机、SSE 事件流、质量门禁、失败收敛和可观测输出。

艺术家迭戈（Diego Velazquez），他被普遍认为是西班牙黄金时代最重要的画家之一，也是西方艺术史上的巨匠，他擅长把口头或场景的“叙述”转化为极具真实感和心理深度的画面。

## 0. 版本里程碑

- 2026-04-12：自由模式（`scratch`）V1 完成，已打通从大纲到逐页生成、compile bundle、可选编译与 QA/修复的主链路。

## 1. 当前功能

### 1.1 主流程闭环

`需求分析 -> 大纲生成(流式) -> 大纲确认 -> 逐页生成/模板编辑 -> generation-owned result -> 可选编译/导出 -> artifact return`

### 1.2 功能矩阵

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 大纲生成与确认闸门 | 已实现 | 支持流式 token 输出、版本化大纲、确认前不可进入生成 |
| Scratch 生成 | 已实现 | 逐页生成 `slide-xx.js`、引用、报告与 compile bundle |
| Template 编辑 | 已实现 | 上传 `.pptx` 模板并生成编辑结果与中间工件 |
| 素材检索与注入 | 已实现 | 支持 `mock/none/auto/unsplash/pexels`，并有并发闸门与去重策略 |
| 视觉策略控制 | 已实现 | `auto / media_required / basic_graphics_only` |
| 质量门禁与修复 | 已实现 | 预览 QA、图表真实性检查、修复轮次与失败诊断 |
| 外部编译集成 | 已实现 | 支持显式 `external compile provider seam`，当前 provider 示例包括 `local` 与 `pagevra` |
| 外部预览集成 | 已实现 | Slide preview 可显式接入 `pagevra`，默认关闭、按需启用 |
| 可观测性 | 已实现 | `run_id/trace_id/stage_timings/error_code/events` |

边界说明：

- `Diego 负责生成`：大纲、逐页 JS、引用、研究/质量报告、compile bundle。
- `外部 compile provider 负责渲染/编译/导出`：当被显式配置时，消费 Diego 的 compile bundle 并返回导出产物。
- `Pagevra` 是当前支持的 provider 之一，不是 Diego 的 ontology center。
- 两者可以组合，但 `Pagevra` 不是 Diego 的 repo-level destiny；默认配置下 Diego 不依赖它才能成功完成 generation。
- `Diego` 也可以提供 host-agnostic 的 long-form drafting primitive：source-aware plan、section-aware revision、structured draft output。
- 对 long-form 而言，Diego 只拥有 drafting truth；其 canonical output 是轻量通用内容对象 `content_blocks_v1`，不拥有 markdown render、preview、docx/export 或任何宿主落地责任。

### 1.3 模块结构（重构后）

- `service/api`: FastAPI 路由与 SSE 出口
- `service/run`: 运行编排与状态机
  - `service/run/flows`: `outline` / `scratch` / `template`
  - `service/run/services`: compile / quality_repair / reporting
- `service/llm`: 大模型客户端、协议适配、解析工具
- `service/design`: 风格策略与主题映射
- `service/slides`: scratch 侧 JS 合约与质量校验
- `service/templates`: 模板结构处理、槽位映射、素材检索
- `service/infra`: 内存存储与事件等待
- `service/models`: API 契约模型

`service/llm` 进一步按责任拆分为显式模块：

- `client.py`: 对外门面与兼容入口
- `transport.py`: provider 请求、重试与文本清洗
- `response_formats.py`: structured output schema 定义
- `outline_prompt_client.py`: outline/research prompt 生成
- `longform_planning_client.py`: long-form plan/research/repair/critique
- `longform_drafting_client.py`: long-form section drafting/revision
- `slide_codegen_client.py`: slide JS codegen
- `slide_spec_client.py`: slide spec generation
- `slide_response_parsers.py` / `outline_normalization.py` / `parsing.py`: 明确 owned 的解析与归一化逻辑

治理原则：

- 不把新能力重新堆回 `service/llm/client.py`
- 不引入 `helpers.py`、`utils.py`、`common.py`、`misc.py` 这类语义不清的 dumping ground
- 运行时依赖拆分优先通过架构澄清推进，而不是先盲目删除 `Node`、`markitdown[pptx]` 或 `asyncpg`

兼容性说明：

- 旧导入路径（如 `service.orchestrator`、`service.llm_client`）仍可用，通过 shim 转发。
- 设置 `PPT_AGENT_SHIM_WARNINGS=1` 可显示旧路径弃用告警。

## 2. 启动与配置

### 2.1 快速启动

```powershell
# 1) 创建虚拟环境
D:\program\Anaconda\python.exe -m venv .venv

# 2) 安装依赖
.\.venv\Scripts\python.exe -m pip install -e .[dev]
npm install

# 3) 初始化配置
Copy-Item .env.example .env

# 4) 启动服务
.\.venv\Scripts\python.exe .\scripts\run_dev.py
```

默认地址：`http://127.0.0.1:8000`

### 2.2 核心环境变量

必填：

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

关键可选：

- `LLM_API_STYLE`: `openai_chat | anthropic_messages`
- `GENERATION_ENGINE`: `agentic_v2 | legacy`
- `STRATUMIND_BASE_URL`: 例如 `http://stratumind:8110`
- `STRATUMIND_TIMEOUT_SECONDS`
- `DIEGO_RAG_TOP_K`
- `COMPILE_PROVIDER`: `none | local | pagevra`，默认 `none`
- `PAGEVRA_PREVIEW_ENABLED`: `0 | 1`，默认 `0`，仅在需要外部 SVG preview 时启用
- `ASSET_PROVIDER`: `mock | none | auto | unsplash | pexels`
- `UNSPLASH_ACCESS_KEY` / `PEXELS_API_KEY`
- `DIEGO_SLIDE_GENERATION_TIMEOUT_SEC`: slide 生成阶段总超时，必须不小于 `300` 秒，默认 `900`
- `QA_FINALIZE_TIMEOUT_SEC`

完整列表见 [`.env.example`](./.env.example)。

### 2.3 Docker 微服务部署（生产基线）

```powershell
# 1) 初始化环境变量
Copy-Item .env.example .env

# 2) 编辑 .env，至少填入 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL

# 3) 构建并启动
docker compose build
docker compose up -d
```

常用运维命令：

```powershell
# 查看状态与健康检查
docker compose ps

# 查看服务日志
docker compose logs -f diego-service

# 停止并移除容器
docker compose down
```

说明：

- Compose 服务名为 `diego-service`，默认映射到 `http://127.0.0.1:8000`。
- 健康检查探针为 `GET /healthz`。
- 默认以 `DIEGO_RUN_STORE=postgres` 持久化 run 元数据，并挂载 `diego-runtime` volume 保留 `.runtime` 产物。
- `DIEGO_DATABASE_URL` 仅在 `DIEGO_RUN_STORE=postgres` 时必需；`memory` 模式不要求数据库。
- 若切回 `DIEGO_RUN_STORE=memory`，容器重启会丢失内存态 run。

## 3. 接口说明

### 3.1 接口总览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 容器健康检查 |
| `POST` | `/v1/ppt/runs` | 用结构化请求创建 run |
| `POST` | `/v1/ppt/runs/prompt` | 用 prompt 快速创建 run |
| `POST` | `/v1/content/runs` | 用结构化请求创建 long-form run |
| `POST` | `/v1/content/runs/prompt` | 用 prompt 快速创建 long-form run |
| `GET` | `/v1/ppt/runs/{run_id}` | 查询 run 详情（含报告与事件） |
| `GET` | `/v1/ppt/runs/{run_id}/events` | SSE 订阅事件 |
| `GET` | `/v1/content/runs/{run_id}` | 查询 long-form run 详情 |
| `GET` | `/v1/content/runs/{run_id}/events` | 订阅 long-form 事件 |
| `GET` | `/v1/ppt/runs/{run_id}/artifacts/compile-bundle` | 返回 scratch compile bundle |
| `POST` | `/v1/ppt/runs/{run_id}/outline/confirm` | 确认或修改大纲 |
| `POST` | `/v1/content/runs/{run_id}/plan/confirm` | 确认或修改 long-form plan |
| `POST` | `/v1/content/runs/{run_id}/sections/{section_id}/revise` | 局部修订指定 section |
| `POST` | `/v1/ppt/templates` | 上传模板 `.pptx` |
| `GET` | `/v1/ppt/templates/{template_id}` | 查询模板元数据 |

### 3.2 请求契约

#### A. CreateRunRequest (`POST /v1/ppt/runs`)

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `topic` | `string` | 是 | - | 主题 |
| `project_id` | `string` | 是 | - | 项目标识 |
| `rag_source_ids` | `string[]` | 否 | `[]` | RAG 文件过滤条件；为空时检索整个项目库，非空时仅检索选中文件 |
| `template_style` | `string` | 否 | `default` | 风格提示 |
| `style_preset` | `string` | 否 | `auto` | 风格预设（会归一化并校验） |
| `target_slide_count` | `int` | 否 | `8` | 目标页数，范围 `1..50` |
| `generation_mode` | `scratch | template` | 否 | `scratch` | 生成模式 |
| `template_id` | `string` | 条件必填 | `null` | `generation_mode=template` 时必填 |
| `visual_policy` | `auto | media_required | basic_graphics_only` | 否 | `auto` | 视觉策略 |

示例：

```json
{
  "topic": "新能源汽车供应链趋势",
  "project_id": "proj-20260412",
  "rag_source_ids": ["chunk-11", "chunk-18"],
  "template_style": "business",
  "style_preset": "auto",
  "target_slide_count": 10,
  "generation_mode": "scratch",
  "visual_policy": "media_required"
}
```

#### B. PromptRunRequest (`POST /v1/ppt/runs/prompt`)

与 `CreateRunRequest` 基本一致，但使用 `prompt` 代替 `topic`，`project_id` 默认 `default-project`。

#### C. ConfirmOutlineRequest (`POST /v1/ppt/runs/{run_id}/outline/confirm`)

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `approved` | `bool` | 否（默认 `true`） | 是否确认大纲并继续执行 |
| `outline` | `OutlineDocument` | 否 | 提交修改版大纲 |
| `base_version` | `int` | 条件必填 | 提交 `outline` 时必须提供并匹配当前版本 |
| `change_reason` | `string` | 否 | 修改原因，必须与 `outline` 同时出现 |

### 3.3 响应契约

#### RunSummaryResponse

用于创建 run 和确认大纲接口：

```json
{
  "run_id": "string",
  "trace_id": "string",
  "status": "OUTLINE_DRAFTING"
}
```

#### RunDetailResponse (`GET /v1/ppt/runs/{run_id}`)

主要字段：

- 基础：`run_id`、`trace_id`、`status`
- 内容：`outline`、`outline_history`、`slides`、`citation_map`
- generation-owned result：`generation_result`
- generation-owned compile handoff：`compile_bundle`
- external compile/export result：`compile_result`
- 兼容字段（legacy mirror）：`compile_js_path`、`pptx_path`、`compile_provider`
- 可观测：`stage_timings`、`events`
- 失败：`error_code`、`failed_stage`、`retryable`、`error_details`
- 报告：`qa_report`、`quality_gate_report`、`research_report`、`template_mapping_report`、`chart_truth_report`、`template_layout_report` 等

语义说明：

- `generation_result` 是 Diego 自有的 generation truth。
- `compile_bundle` 是 Diego 产出的 downstream handoff artifact，用于显式 compile seam。
- `compile_result` 只描述显式 compile provider outcome；未请求 provider 时不应吞回 Diego 自有 generation truth。
- `template` 模式下由 Diego 直接产出的 `.pptx` 仍通过 `artifacts.pptx` / `pptx_path` 暴露，但不应被解释成 external provider result。

#### 模板接口返回

- `POST /v1/ppt/templates`:

```json
{
  "template_id": "string",
  "filename": "template.pptx"
}
```

- `GET /v1/ppt/templates/{template_id}`:

```json
{
  "template_id": "string",
  "filename": "template.pptx",
  "path": "string",
  "created_at": "ISO-8601"
}
```

### 3.4 SSE 事件流接口

`GET /v1/ppt/runs/{run_id}/events` 返回 `text/event-stream`：

- `event:` 为事件名（如 `outline.completed`）
- `data:` 为 `RunEvent` JSON（`seq/event/ts/payload`）
- 空闲时会输出 `: keep-alive`
- run 进入 `SUCCEEDED` 或 `FAILED` 后流结束

示例：

```text
event: slide.generated
data: {"seq":27,"event":"slide.generated","ts":"2026-04-12T10:00:00Z","payload":{"slide_no":3,"status":"generated"}}
```

## 4. 状态与事件

### 4.1 状态机

- `OUTLINE_DRAFTING`
- `AWAITING_OUTLINE_CONFIRM`
- `SLIDES_GENERATING`
- `COMPILING`
- `SUCCEEDED`
- `FAILED`

约束：

- 不允许绕过 `AWAITING_OUTLINE_CONFIRM`。
- 失败态必须提供 `error_code` 与 `failed_stage`。

### 4.2 事件集合

最小可消费事件：

- `outline.token`
- `outline.completed`
- `slide.generated`
- `compile.completed`
- `run.failed`

常用扩展事件：

- 需求/计划：`requirements.analyzing.*`、`research.completed`、`plan.completed`
- 生成：`slide.started`、`slide.failed`、`slide.codegen.*`、`slide.selection.completed`
- 质量：`slide.preview.qa`、`qa.completed`、`repair.*`、`chart.truth.checked`
- 模板：`slot.mapping.completed`、`template.layout.reflow.completed`、`template.fidelity.checked`
- 收尾：`artifact.cleanup.completed`、`run.finalized`

完整枚举见 [`service/models/contracts.py`](./service/models/contracts.py) 的 `EventType`。

## 5. 错误处理

### 5.1 HTTP 层

- `400`：模板文件非法（非 `.pptx` 或空文件）
- `404`：`run_id` / `template_id` 不存在
- `409`：确认大纲冲突（状态非法、版本不匹配）
- `422`：请求字段校验失败

### 5.2 运行层 (`run.failed`)

常见 `error_code`：

- 大纲阶段：`OUTLINE_LLM_TIMEOUT`、`OUTLINE_LLM_ERROR`、`OUTLINE_REPAIR_EXHAUSTED`
- 生成阶段：`SLIDE_LLM_ERROR`、`SLIDE_GENERATION_TIMEOUT`、`VISUAL_POLICY_UNSATISFIED`
- 模板阶段：`TEMPLATE_ID_MISSING`、`TEMPLATE_NOT_FOUND`、`TEMPLATE_ASSET_FETCH_FAILED`、`TEMPLATE_SLOT_UNMAPPED`、`TEMPLATE_LAYOUT_CONFLICT`
- 编译/收尾：`COMPILE_SCRIPT_FAILED`、`TEMPLATE_JS_COMPILE_FAILED`、`QA_FAILED`、`FINALIZE_TIMEOUT`

排障建议：使用 `GET /v1/ppt/runs/{run_id}` 读取 `error_details`、`events` 和各类 report。

## 6. 产物结构

### 6.1 Scratch 模式

`artifact_dir` 下典型产物：

- `slides/slide-xx.js`
- `slides/compile.js`
- `slides/output/presentation.pptx`
- `slides/imgs/*`（需要素材时）

### 6.2 Template 模式

`artifact_dir` 下典型产物：

- `template_edit/template.pptx`
- `template_edit/edited.pptx`
- `template_slides/slide-xx.js`
- `template_slides/compile.js`
- `template_slides/output/presentation.pptx`（模板 JS 编译校验产物）

接口返回以 `generation_result`、`compile_bundle`、`compile_result` 为主。
其中 `pptx_path`、`compile_js_path`、`compile_provider`、`compile_fallback_used` 仅作为兼容镜像保留；文件可见性优先看 `artifacts`，provider outcome 优先看 `compile_result`。

## 7. 调试与测试

### 7.1 终端交互调试

```powershell
.\.venv\Scripts\python.exe .\scripts\run_cli.py
```

可直接完成：输入 prompt、查看/编辑大纲、确认执行、查看 `generation_result` / `compile_result`、产物路径与关键事件。

### 7.2 自动化测试

```powershell
New-Item -ItemType Directory -Force -Path .runtime,.runtime\pytest_tmp,.runtime\pytest_cache | Out-Null
$env:TEMP=(Resolve-Path '.runtime').Path
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime\pytest_tmp -o cache_dir=.runtime\pytest_cache
```

测试分层：

- `tests/integration`: API/SSE/流程集成
- `tests/service`: 业务行为与质量门禁
- `tests/support`: 测试辅助模块

## 8. 相关文档

- [项目目标基线](./docs/PROJECT_GOALS.md)
- [架构与契约](./docs/ARCHITECTURE.md)
- [测试指南](./docs/TESTING_GUIDE.md)
- [未来对接改动点（规划）](./docs/SPECTRA_CHANGE_POINTS.md)

## 9. 当前边界

- 当前阶段聚焦本服务能力，不包含上游系统 UI。
- 当前阶段不修改任何外部系统代码。
