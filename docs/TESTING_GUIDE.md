# Testing Guide

## 1. 当前完成度与可测试性结论

截至当前代码状态，本项目已具备完整测试条件：

- 自动化测试可运行并通过（本地复测：`17 passed`）。
- 自动化测试可运行并通过（本地复测：`18 passed`）。
- 核心链路可测：`大纲生成 -> 大纲确认 -> 逐页生成 -> 编译 -> QA/repair`。
- 双模式可测：`scratch`（自由生成）与 `template`（模板编辑）。
- 新增能力可测：模板槽位语义映射 fail-fast、图表真实性门控、逐页 preview QA 事件。
- 新增能力可测：`agentic_v2` 逐页 codegen/critic 修复、preview 产物自动清理、模板槽位语义映射 fail-fast、图表真实性门控。

## 2. 测试前准备

在仓库根目录执行（PowerShell）：

```powershell
# 1) 安装依赖
.\.venv\Scripts\python.exe -m pip install -e .[dev]
npm install

# 2) 准备运行时目录（避免临时文件散落）
New-Item -ItemType Directory -Force -Path .runtime,.runtime\pytest_tmp,.runtime\pytest_cache | Out-Null
```

## 3. 如何启动测试功能

### 3.1 自动化测试（推荐）

```powershell
$env:TEMP=(Resolve-Path '.runtime').Path
$env:TMP=$env:TEMP
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.runtime\pytest_tmp -o cache_dir=.runtime\pytest_cache
```

仅查看测试项：

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q --basetemp=.runtime\pytest_tmp -o cache_dir=.runtime\pytest_cache
```

### 3.2 本地服务联调（手工）

```powershell
.\.venv\Scripts\python.exe .\scripts\run_dev.py
```

服务地址：`http://127.0.0.1:8000`

## 4. 当前测试项清单

测试文件已按职责拆分：

- `tests/integration/test_api_runs.py`
- `tests/integration/test_template_mode.py`
- `tests/integration/test_events_and_finalize.py`
- `tests/service/test_agentic_qa.py`
- `tests/service/test_llm_resilience.py`
- `tests/service/test_visual_policy.py`

共享测试基座：

- `tests/support/service_flow_shared.py`（mock client、fixture、helper）

结构门禁：

- `tests/service/test_architecture_guards.py`（依赖方向 + shim 导出约束）
- `tests/service/test_file_size_budgets.py`（核心文件行数预算）

上述测试覆盖以下场景：

- 配置与参数校验：缺失 LLM 环境变量、创建 run 参数校验。
- 大纲流程：prompt 创建、确认闸门、大纲版本冲突与更新。
- scratch 主链路：成功生成、repair 使用“最新产物”而非回退 outline。
- template 主链路：模板上传、结构重建、语义占位替换、slot mismatch 清理。
- 失败路径：模板解析失败、模板素材拉取失败、未知槽位 fail-fast（`TEMPLATE_SLOT_UNMAPPED`）。
- 可观测性：SSE 事件最小集合 + `slide.preview.qa`/`chart.truth.checked`。
- agentic 引擎：`slide.codegen.started/completed`、`slide.critic.completed`、`slide.repair.completed`、`artifact.cleanup.completed`。
- 可观测性：SSE 事件最小集合 + `slide.preview.qa`/`chart.truth.checked`。
- 图表真实性：无可核验数值时进入 `qualitative_fallback`，避免伪造数值图表。

## 5. 建议的回归顺序

1. 先跑一次 `pytest` 全量确认回归基线。  
2. 再启动服务做手工 API 流程（scratch 一次、template 一次）。  
3. 最后检查运行详情中的 `template_mapping_report`、`chart_truth_report`、`repair_history`。  
