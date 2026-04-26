# 项目目标基线（PROJECT_GOALS）

## 1. 文档目的与适用范围

本文件定义 `ppt-agent-service` 的唯一目标基线，用于指导实现、测试与验收。

适用范围：
- 适用于本服务自身的产品目标、技术目标和交付标准。
- 适用于后续任何与外部系统的集成设计。

不适用范围：
- 不作为外部系统实现说明书。
- 不作为运维手册或部署 SOP。

可验证条款：
- 任何需求评审必须以本文件为目标依据。
- 新增功能若与本文件冲突，以本文件为准并先更新本文件。

## 2. 北极星目标（1 句话）

在不依赖特定上游系统实现细节的前提下，稳定产出可追溯、可迭代、可观测的高质量 generation result、compile bundle 与可选 compiled artifact。

可验证条款：
- 服务可以独立接收输入并完成端到端 PPT 生成。
- 生成结果包含可追溯引用信息。

## 3. 核心业务目标（用户价值）

- 降低课件制作的人力成本：从主题到 generation result 的自动化链路可复用。
- 提升内容可信度：每页内容可以回溯到检索来源 `chunk_id`。
- 提升交互体验：大纲与逐页生成过程对上游可流式可见。
- 提升可控性：在生成前提供大纲确认/修改关口。
- 对长文生成保持 host-agnostic：支持 source-aware long-form drafting 与 section-aware revision，但不拥有宿主卡片、导出或预览责任。

可验证条款：
- 用户可以在大纲确认后再进入逐页生成。
- 用户可以看到逐页生成进度与失败原因。

## 4. 功能目标（按流程分段）

### 4.1 输入接收

服务必须支持以下输入字段：
- `topic`
- `project_id`
- `rag_source_ids`
- `template_style`
- `target_slide_count`

可验证条款：
- 缺失 `topic` 或 `project_id` 时返回明确参数错误。
- 以上字段在运行上下文中可追踪。

### 4.2 大纲生成

- 支持基于 RAG 上下文生成 `OutlineDocument`。
- 支持大纲流式输出（至少 token 与分段完成事件）。

可验证条款：
- 大纲生成结束后状态进入 `AWAITING_OUTLINE_CONFIRM`。
- 大纲结构满足 `OutlineDocument` 契约。

### 4.3 大纲确认与修改

- 支持接收确认版或修改版大纲。
- 确认后按确认版本继续执行逐页生成。

可验证条款：
- 未确认大纲时不得进入 `SLIDES_GENERATING`。
- 提交修改版后可记录版本与变更原因。

### 4.4 逐页 slide JS 生成

- 每页生成一个 `slide-xx.js`。
- 单页生成失败可重试，成功后立即输出页级事件。

可验证条款：
- 每页至少产生一次 `slide.generated` 或最终失败事件。
- 页码连续，且总页数与大纲目标一致或有差异说明。

### 4.5 编译与外部导出契约

- 生成 `compile.js` 与 compile bundle，供外部编译服务消费。
- Diego 可选接入显式 compile provider，但默认不依赖特定 provider 才能完成主路径。
- generation result、compile bundle、compiled artifact 必须在契约上可区分，不能混成单一模糊结果。
- 兼容字段可以保留，但不得盖过 `generation_result / compile_bundle / compile_result` 的主叙事。
- 返回 `citation_map`，建立“页 -> 来源 chunk”映射。

可验证条款：
- scratch 模式下 compile bundle 可被稳定构建。
- 当显式启用 compile provider 时，导出产物可正常打开。
- `citation_map` 包含至少一个有效 `chunk_id`（当检索命中时）。

### 4.6 事件流目标

事件流至少覆盖：
- `outline.token`
- `outline.completed`
- `slide.generated`
- `compile.completed`
- `run.failed`

可验证条款：
- 全流程运行中可收到上述最小事件集合（成功或失败路径）。

### 4.7 通用长文生成 primitive

- 支持 source-aware long-form planning 与 structured draft generation。
- 支持 section-aware revision，且局部修订不应破坏其它 section 的 truth。
- canonical output 应保持为通用内容对象 `content_blocks_v1`，而不是绑定某个宿主 markdown/docx/export 流程。

可验证条款：
- `content` run 可在确认 plan 后生成 `plan + draft + section revision`。
- long-form 契约不包含 `preview/docx/export/compile provider` 成功语义。

## 5. 非功能目标（稳定性、性能、可观测性、安全）

### 5.1 稳定性

- 状态机不可越序：
  - `OUTLINE_DRAFTING -> AWAITING_OUTLINE_CONFIRM -> SLIDES_GENERATING -> COMPILING -> SUCCEEDED/FAILED`
- 单页失败重试不应导致全局状态混乱。

可验证条款：
- 状态流转日志可证明无非法跳转。

### 5.2 性能

- 逐页生成支持并发执行（并发度可配置）。
- 在同等输入下，阶段耗时可观测并可比较。

可验证条款：
- 运行记录包含 `outline`、`slide`、`compile` 分阶段耗时。

### 5.3 可观测性

每次运行必须具备：
- `run_id`
- `trace_id`
- `stage_timings`
- `error_code`（失败时）

可验证条款：
- 任意失败任务可通过 `run_id` 定位到错误码与失败阶段。

### 5.4 安全

- 不在日志输出敏感密钥。
- 外部调用必须具备最小权限控制策略（由集成环境落地）。

可验证条款：
- 日志采样中不出现明文凭证。

## 6. 明确不做（Non-Goals）

- 不在本服务中实现上游系统 UI。
- 不在本服务中实现通用文件管理平台。
- 不承诺一次性覆盖所有视觉设计风格。
- 不在当前阶段修改任何外部系统代码。

可验证条款：
- 当前阶段交付物仅限本仓库内容。

## 7. 里程碑目标（M0/M1/M2）

### M0：目标与契约冻结

- 完成目标文档、架构文档、未来集成改动清单。
- 固定对象名、状态名、事件名。

验收：
- 文档齐全且命名一致。

### M1：服务最小可运行闭环

- 提供可运行 API 与最小状态机。
- 支持大纲生成、确认、逐页生成、compile bundle 暴露与可选编译集成。

验收：
- 至少 1 个端到端样例成功产出 generation result 与 compile bundle。

### M2：质量与可观测增强

- 完成失败重试、错误码标准化、阶段耗时统计。
- 产出 `citation_map` 并用于结果解释。

验收：
- 失败场景可稳定复现与定位。

## 8. 验收标准（Definition of Done）

满足以下全部条件才视为达到本目标：

- 输入支持：支持 `topic/project_id/rag_source_ids/template_style/target_slide_count`。
- 产出支持：提供 `OutlineDocument`、逐页 `slide-xx.js`、`compile bundle`、`citation_map`。
- 流程闭环：完成 `RAG检索 -> 大纲流式 -> 大纲确认 -> 逐页JS生成 -> generation result 暴露`。
- 当显式启用 compile provider 时，额外验证 compile/export artifact。
- 事件流：至少覆盖 `outline.token`、`outline.completed`、`slide.generated`、`compile.completed`、`run.failed`。
- 失败处理：单页失败可重试；运行级错误可定位；状态机不可越序。
- 可观测：每次 run 必有 `run_id/trace_id/阶段耗时/错误码`。
- 质量：PPT 可打开；页数与大纲一致（或有记录化差异说明）；引用可追溯到 `chunk_id`。

## 9. 与 Spectra 的未来集成边界（仅描述，不实施）

- 本服务未来可作为外部生成引擎被 Spectra 调用。
- Spectra 负责会话 UI、确认交互、下载入口；本服务负责生成编排与产物生成。
- 具体改动点统一记录在 `docs/SPECTRA_CHANGE_POINTS.md`。

约束：
- 当前阶段不实施任何 Spectra 代码改动。
- 当前阶段不提交任何 Spectra 仓库变更。
