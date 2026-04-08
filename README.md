# ppt-agent-service

`ppt-agent-service` 是一个与上游业务系统解耦的 PPT 生成微服务，负责把主题与资料范围转为可追溯的课件产物。

## 项目目标摘要

- 提供完整闭环：`RAG检索 -> 大纲流式 -> 大纲确认 -> 逐页 JS 生成 -> 编译 -> PPTX 产物返回`。
- 标准输入：`topic/project_id/rag_source_ids/template_style/target_slide_count`。
- 标准输出：`OutlineDocument`、逐页 `slide-xx.js`、最终 `pptx`、`citation_map`。
- 提供可消费事件流，至少覆盖：`outline.token`、`outline.completed`、`slide.generated`、`compile.completed`、`run.failed`。
- 全链路可观测：每次运行必须记录 `run_id`、`trace_id`、阶段耗时与错误码。

完整规范见：[PROJECT_GOALS.md](./docs/PROJECT_GOALS.md)

## 文档目录

- [项目目标基线](./docs/PROJECT_GOALS.md)
- [架构与契约](./docs/ARCHITECTURE.md)
- [未来对接改动点（仅计划）](./docs/SPECTRA_CHANGE_POINTS.md)

## 当前阶段边界

- 当前阶段只建设本项目文档与新服务自身实现。
- 当前阶段不修改任何外部系统代码。
