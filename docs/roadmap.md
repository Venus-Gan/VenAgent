# VenAgent 剩余功能路线（Roadmap）

来源：Wayfinder 票 `剩余功能规划`（resolved）。本文件是剩余功能规划的唯一正文；模块实施细节以各模块开发时的 Wayfinder 票为准。

> **状态（2026-08-30 代码核实更新）**：路线全部模块已实现；「可靠 agent」最小跑通集已通过真实环境验收（见 `docs/wayfinder/assets/m07-intake.md` §10）。当前进行「收尾事项」（见文末）：目录平整（形态 C：`venagent/` → `src/`，ADR-0010）与提交入库；不再有功能缺口。

## 总体完成标准（"可靠 agent"）

路线模块全部实现 + 真实多步任务跑通。

**最小跑通集**：单多步任务 = ≥2 次工具调用 + 1 次 M06 审批 + 中途断线恢复后完成。浏览器 Verify 覆盖四要素：发送 / 流式 / 恢复 / 审批；外加工具副作用幂等、跨 owner 隔离。

**达成情况（2026-08-30）**：✅ 全部达成——最小跑通集实弹验证见 `docs/wayfinder/assets/m07-intake.md` §10 场景①（多工具 + 审批 + 断线恢复实测）；浏览器四要素由前端 E2E 覆盖（m07 §9 记录 E2E 21 passed；前端工具失败可见性票记录 E2E 20 passed）。

## 子模块顺序（Q1 锁定）

1. **M06 单工具闭环（基线）** — ✅ 已实现（graph.py 5 节点，现为 M07 superset 图的基线支；单回合工具调用数过渡期限制 1 已随多工具放开）。
2. **多工具（第一版纯顺序执行）** — ✅ 已落地（`RUNTIME_CONTRACT_VERSION=3`、`pending_tool_calls` 队列 + `model_finalize` 条件回环，测试 `tests/agent/test_agent_tool_loop.py`）；层内并行（MaxParallel 2）/ 竞速（RaceGroup）已随 M07 实现，不再是"后续增强"。
3. **M08 RAG** — ✅ 已实现：三路 RRF 引擎（`venagent/rag/`）+ per-owner 文档库状态机 + documents API + `/rag` 命令 + `rag_search` 工具（safe + Loaded 前置 + 不可用隐藏）；Milvus/ES 客户端 `venagent/platform/{milvus,es}.py` + `compose.yaml` 服务。接入点在 bootstrap/计划层（见「现状事实」）。
4. **memory / promptctx 重构落地** — ✅ 已实现：目录树定稿 P9 六组合并落地（`venagent/memory/` 16 文件，含 `embedding/`、`graph_memory/`、`long_term/` 子包）+ 会话路径收敛 `repo/inmemory/`（ADR-0001/0002）+ 长期记忆沉淀（ADR-0008，已实现）。⚠️ M07 定稿的 promptctx `source_planner.py` / `source_rag.py` 未建（偏差，见「收尾事项」2）。
5. **sandbox / skills / MCP / command 对齐与验证** — ✅ 已实现（现状调查确认功能完整；验证即完成口径已达成，相关 pytest 绿）。
6. **路由 + 动态图编排整合（langgraph 特色，最后）** — ✅ 已实现并真实环境验收（`m07-intake.md` §10 六场景 + 任务视窗全通过）。

## 每模块完成标准（Q2）

**总口径**：功能完整 + 相关 pytest 绿 + 按风险定级 Verify（HTTP 级或浏览器级，按模块风险选择）；不做全仓覆盖率门槛。

- **M06 基线**：验收使用「新目录树 + 测试重写后」的测试（tests/agent/），**不**使用现有测试（现有测试/日志/文档后续会被清理，关联 tests 重组规范票）。—— ✅ 已完成（`tests/agent/` 11 文件；tests 重组规范 D1–D10 已落地）。
- **多工具**：HTTP 级前置验证；断线恢复验证留 M07。—— ✅ 已完成（断线恢复随 M07 §10 场景① 实测）。
- **M08 RAG**：含真实 Milvus/ES 集成测试（compose 起服务）。—— ✅ 已实现（`compose.yaml` milvus/es；m07 §9 记录 rag-dense/rag-keyword ready；测试见 `tests/rag/`、`tests/document/`）。
- **memory/promptctx 重构**：目录树归位后相关 pytest 全绿 + 一次真实场景 Verify。—— ✅ 已达成（出沙箱口径 421 passed；m07 验收场景覆盖记忆链路）。
- **对齐与验证**：功能完整 + 相关 pytest 绿（行为不变，验证即完成）。—— ✅ 已达成。
- **路由 + 编排整合**：最小跑通集 + 浏览器四要素 Verify；场景细化见 M07 设计定稿（`docs/wayfinder/assets/m07-intake.md` §8，2026-08-29 三轮 grilling 拍板）。—— ✅ 已达成（§10 六场景全过，11 项修复均带回归）。

## 现状事实（2026-08-30 代码核实更新）

> 上一版「现状事实」（2026-08-29）中『RAG 未接入主链路 / RunPhase planning·replanning 惰性 / `deciding` 不在 Literal』三条为 **M07 整合前的快照，已失效**；以下为按当前工作树核实后的现行事实。

- **分支与入库状态**：分支 `codex/memory-system-refactor`；**提交入库已启动**（2026-08-30）——弃用内容清理（C1：docs/comet、final、旧 memory/repo-temporary、tests 根平铺测试、根 mcp/）、`.gitignore` 修复与 M06 MCP 客户端入库（C2）、M06 工具面/技能/沙箱/命令支撑（C2.5）、M08 RAG 与文档库（C3）已提交，共 4 个 commit（89ca1cb / 9a828b3 / 65e9ad6 / 45063d1）；其余（M07 计划层、记忆系统、config、前端、docs、src 改名）工作树待收尾。
- **M06 / 多工具**：`graph.py:28` `RUNTIME_CONTRACT_VERSION = 3` + `pending_tool_calls` 条件回环；测试 `tests/agent/`（11 文件）。
- **M07 路由 + 动态图编排**：已实现并验收。计划层 `venagent/agent/planning/`（dag/selector/planner/executor/replanner/factory + `subagents/`）；`runtime.py:342-380` 按 `PlanningRuntime.enabled` 接线 selector/planner/executor/replanner/generator/rag_answer 节点；`bootstrap.py:412-418` 装配（`config.planning`，AppConfig 定义于 `config/models.py:366`，planning 字段 :385）。
- **RunPhase**（`agent/state.py:187-195`）：Literal 含 `planning`/`replanning`；原 `"deciding"` 漂移已修（m07 §9 顺手项 → `"selecting_tools"`）。
- **RAG 接入**：`bootstrap.py` — `_build_rag_search`（:667）构建 HybridSearchService；`rag_search` 工具注册（:316-345，Gateway 执行分支，safe + Loaded 前置 + 不可用目录隐藏）；`RagCommandAdapter`（:435）提供 `/rag` 命令；计划层 `factory.py:234+` rag_answer 节点调用 `rag_search.search`（[n] 编号引用 + 来源不足说明）。`venagent/rag/` 16 文件 + `venagent/platform/{milvus,es}.py` + `compose.yaml`（milvus/es）。per-owner：gateway executor 契约扩展 owner_id（m07 §9 修复 1）。
- **memory/promptctx 重构**：`venagent/memory/` 16 文件（recall/management/jobs/model_adapters/service/short_term + `embedding/`、`graph_memory/`、`long_term/` 子包）；`repo/inmemory/` 会话路径收敛；长期记忆沉淀已实现（`memory/service.py:379`、`repo/postgresql/memory/jobs.py:252`；ADR-0008）。
- **config 全量迁移**：`.env` 已删；`config/models.py` + `config/loader.py` + `config.example.yaml`；前端 `/settings`（`web/src/app/router.ts` → `web/src/modules/settings/SettingsPage.vue`）。
- **前端**：任务视窗（`ChatWorkspace.vue`）、澄清/审批卡片、run 事件标签（route/plan/node/race/clarification）；E2E specs 5 个（m06 / m06.real / memory / memory.real / workspace）。
- **测试（2026-08-30 本机核实）**：`pytest tests -m "not integration"` 隔离环境 = 413 passed / 8 failed / 14 deselected；8 个失败全部为 `tests/mcp/test_m06_mcp.py` 的 stdio 子进程用例（`McpConnectionError: mcp_process_start_failed`）——执行沙箱禁止 piped-stdio 子进程所致，代表用例出沙箱复跑通过；按出沙箱口径 **421 passed**，与 m07 §10 验收后清理记录一致。m07 §9 另有记录：406 passed（该次口径）+ tests/repo 集成 25/25 + ruff 绿（仅剩 `tests/rag/test_hybrid.py:175` HEAD 既有 F841）。

## 收尾事项（2026-08-30，实现完成后的剩余操作）

> 这些不是功能缺口，是"项目整体完成"的最后几步。

1. **提交入库**：~~全部实现产物未跟踪~~ —— 已启动（2026-08-30，见「分支与入库状态」）。提交策略经用户拍板调整为「先文档、commit 最后统一」：文档与代码收尾后再整体 commit（M 文件按「整文件归主主题」，不拆 hunk；形态 C src 改名作为最后一个 commit）。
2. **M07 定稿偏差处置**：~~已关闭（2026-08-30）~~。m07-intake.md §8-10 要求的 `promptctx/source_planner.py`、`source_rag.py` 未建——经 AGI-saber 实证（`D:\VSCProject\AGI-saber` 的 memPrefix + 节点内联模式）确认定稿与实证不符，用户拍板 C'：保留节点内联 + 每 run 一次统一 `mem_prefix` 投影装配 + 不建 source_rag + source_planner 语义更正为任务状态跨轮快照（Phase 2 可选）。已实施：`runtime.py:_build_planning_mem_prefix` + factory/planner/replanner 四节点前缀注入，测试 429 passed；m07-intake.md §8 第 4/8/10 条已按实证改写，结论沉淀为 ADR-0009。
3. **README 架构图重画**：README 架构图仍为旧实现描述（map.md 已注明「整图重画另行处理」）——已纳入本次文档整理：与形态 C 布局（ADR-0010）一并更新 README 目录树与启动说明（`python -m src`）、mcp-configs 运行时目录说明。
4. **遗留测试账号处置**：历史遗留账号 m05_*/e2e_rag_*/diag_* 等 17 个（含会话/run/文档）待用户拍板是否批量清除（m07 §10 遗留与建议）。
5. **低优先级前端小问题**：浏览器斜杠菜单打开时 Enter 偶发不提交（m07 §10 遗留与建议）。

## 关联决策

- ADR-0003（执行权威归 M06）、ADR-0005（正交分层）、ADR-0006（RAG 三路 RRF）、ADR-0007（Selector 隐性分发）、ADR-0002（目录树与测试归位）。
