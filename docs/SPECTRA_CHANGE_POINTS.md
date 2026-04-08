# Spectra 未来改动点清单（仅计划，不实施）

> 本文件只记录未来集成改动点。当前阶段禁止修改 Spectra 代码。

## 1. 调用入口改动点

未来需要在 Spectra 增加或调整以下调用流程：

- 发起生成：调用 `POST /v1/ppt/runs`
- 订阅进度：消费 `GET /v1/ppt/runs/{run_id}/events`
- 大纲确认：调用 `POST /v1/ppt/runs/{run_id}/outline/confirm`
- 拉取结果：调用 `GET /v1/ppt/runs/{run_id}`

## 2. 事件消费改动点

Spectra 未来需消费并映射以下事件：

- `outline.token`（大纲逐字/增量展示）
- `outline.completed`（大纲草拟完成）
- `slide.generated`（单页生成完成）
- `compile.completed`（最终产物完成）
- `run.failed`（失败提示与重试入口）

## 3. 大纲确认回调改动点

Spectra 未来需提供交互能力：

- 展示草拟大纲（`OutlineDocument`）
- 支持用户确认或修改后提交
- 提交时带 `base_version` 与 `change_reason`

## 4. 结果接收与下载改动点

Spectra 未来需新增结果接收映射：

- 接收 `pptx` 产物信息
- 接收逐页 `slide-xx.js` 元数据（用于调试或审计）
- 接收 `citation_map` 用于引用溯源展示

## 5. 运行态与错误态映射改动点

Spectra 未来需对齐以下状态：

- `OUTLINE_DRAFTING`
- `AWAITING_OUTLINE_CONFIRM`
- `SLIDES_GENERATING`
- `COMPILING`
- `SUCCEEDED`
- `FAILED`

并映射错误字段：
- `error_code`
- `failed_stage`
- `retryable`

## 6. 当前阶段声明

- 本文档中的改动点仅为后续集成计划。
- 本阶段不在 Spectra 仓库实施任何代码、配置、数据库或接口变更。
