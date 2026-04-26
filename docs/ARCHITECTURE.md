# 架构与契约（ARCHITECTURE）

## 1. 架构目标

`ppt-agent-service` 作为独立微服务，面向任何上游系统提供统一的生成能力。

核心闭环：
`RAG检索 -> 大纲流式 -> 大纲确认 -> 逐页 JS 生成 -> generation truth -> external compile provider -> render/export artifact`

边界定义：
- Diego owns `generation truth`
- Diego owns `generation result` and `compile bundle truth`
- Diego does not own `render truth`
- compile/export 通过 `external compile provider` seam 接入
- slide preview 通过可选 `external preview provider` seam 接入
- `pagevra` 是当前 supported provider 之一，不是默认骨架
- 对 long-form 而言，Diego owns `drafting truth`，其 canonical output 是 `content_blocks_v1`，但 does not own markdown render, preview, docx, or export truth

## 1.1 服务内部分层（2026-04 重构后）

- `api`: FastAPI 路由与 SSE 出口
- `run`: 运行编排、状态流转、失败收敛
  - `run/flows`: `outline_flow` / `scratch_flow` / `template_flow` 主流程执行器
  - `run/services`: `quality_repair_service` / `compile_service` / `reporting_service` 领域服务
    - `orchestrator` 仅保留生命周期编排与失败收敛，重逻辑下沉到 services
- `llm`: provider 调用、协议与输出解析
- `slides`: scratch 侧 JS 合约校验、质量门禁、诊断
- `templates`: 模板结构重建、slot mapping、layout reflow、素材注入
- `design`: 样式策略与主题映射
- `infra`: 内存存储与事件等待机制
- `models`: API/状态对象契约
- `content`: host-agnostic long-form planning, drafting, and section revision

兼容层策略：
- `service.orchestrator`、`service.llm_client` 等旧路径仍保留为 shim。
- shim 默认静默；设置 `PPT_AGENT_SHIM_WARNINGS=1` 时会抛出弃用告警，便于迁移。

## 2. 运行状态机

- `OUTLINE_DRAFTING`
- `AWAITING_OUTLINE_CONFIRM`
- `SLIDES_GENERATING`
- `COMPILING`
- `SUCCEEDED`
- `FAILED`

状态约束：
- 不允许跳过 `AWAITING_OUTLINE_CONFIRM` 直接进入 `SLIDES_GENERATING`。
- `FAILED` 必须附带 `error_code` 和 `failed_stage`。

## 3. 核心对象契约

### OutlineDocument

- `version: int`
- `nodes: list`
- `summary: string`

### SlideArtifact

- `slide_no: int`
- `js_code: string`
- `status: string`
- `citations: list[string]`

### citation_map

- 结构：`{ slide_no: [chunk_id, ...] }`

## 4. API 契约（v1）

- `POST /v1/ppt/runs`
  - 创建运行，进入 `OUTLINE_DRAFTING`
- `GET /v1/ppt/runs/{run_id}`
  - 查询运行状态与结果
- `GET /v1/ppt/runs/{run_id}/events` (SSE)
  - 消费流式事件
- `POST /v1/ppt/runs/{run_id}/outline/confirm`
  - 提交确认版/修改版大纲并继续执行

## 5. 事件流最小集合

- `outline.token`
- `outline.completed`
- `slide.generated`
- `compile.completed`
- `run.failed`

推荐扩展事件：
- `outline.section.generated`
- `slide.started`
- `slide.js.partial`
- `compile.started`

## 6. 编译边界

- `build_compile_bundle` 是 Diego 对外的一等 contract。
- 默认 `compile_provider=none`，表示 Diego 完成 generation 后只暴露 compile bundle，不主动编译。
- `compile_provider=local` 或 `compile_provider=pagevra` 时，编译作为显式 adapter 行为执行。
- `template` 模式下 Diego 自己产出的 `.pptx` 属于 generation-owned output，不应伪装成 provider seam outcome。
- `compile_js_path`、`pptx_path`、`compile_provider` 等兼容字段只作为 legacy mirror 暴露，不应反客为主。
- 默认 `pagevra_preview_enabled=0`，表示 Diego 不把外部 preview 当默认主路径。
- 不允许通过 fallback 把 provider 边界错误伪装成 Diego 自身成功。

## 7. 失败与重试策略

- 单页失败：按页重试，不立即中断整个 run。
- 编译失败：直接进入 `FAILED`，保留中间产物元数据用于排障。
- 所有失败必须可通过 `run_id` 回溯。

## 8. 可观测性要求

每次 run 必须写入：
- `run_id`
- `trace_id`
- `stage_timings`（outline/slide/compile）
- `error_code`（失败场景）

## 9. 当前阶段边界

- 本文档仅定义新服务实现基线。
- 当前阶段不修改任何外部系统代码。
- 新增 long-form primitive 时，不得引入宿主卡片 ontology，也不得把 compile/export/preview 责任长进 Diego。
