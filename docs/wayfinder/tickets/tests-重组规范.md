---
wayfinder: ticket
id: tests-restructure
title: tests/ 重组规范（命名归属、fixtures、删重复断言）
labels: [wayfinder:grilling]
blocked_by: []
status: resolved
claimed_by: captain
resolved_comment: 用户 3 批 10 项逐块拍板（归位映射/M06 重写+非 M06 归位保留/特殊件/fixtures 删除模拟器/conftest 拆分/marker 单开关/五条治理规则）；Resolution 已写入执行设计 4 阶段与验证方案 6 条。map.md Decisions so far 已同步。
---

## Question

tests/ 现状：test_m06_*（agent_tool_loop, langgraph, mcp, memory_integration, persistence, skill_hub, tools）+ test_run_events + 大量已改但命名仍按旧模块的文件；fixtures/ 未跟踪。用户：「现有代码跟测试是正确做的，我觉得太过注重于验证了」。定：测试文件如何按新目录树归属命名、fixtures 如何集中、哪些重复断言可删、单元（mock/降级后端）与需 PG/Docker 的集成如何区分标记。目标：**测试是行为契约，不是验证过载**。

## Context

用户 Q2b；「验证过重」实锤证据：.tmp 五份 M06 验收整改计划循环（m06-final-three-blockers-remediation-plan / m06-final-acceptance-followup-remediation-plan / m06-remaining-capability-remediation-plan / m06-single-tool-loop-fix-plan / m06-tool-loop-acceptance-remediation-plan）、project_tool_result 九元组校验、InvariantRunTransition 先对账再取消、每模块独立 errors.py、docs/comet 1516 文件流程产物。README 已验证命令（工程一致）：migrate 是唯一 DDL 入口；venagent_test 独立库跑真 PG、TEST_NEO4J_URI 显式才跑真 Neo4j；VENAGENT_INVOCATION_ENCRYPTION_KEY 32 字节 Base64、持久模式缺失时 fail closed。已跑单元面：test_m06_tools.py=20 passed；test_m06_langgraph.py+test_m06_agent_tool_loop.py=31 passed+3 skipped（skip=需 PG/Docker）。

## Context（现状调查 ba4a0547 → assets/tests-现状调查.md，只读）

- **规模**：tests/ 33 .py（30 测试文件 + conftest.py 95 行 + fixtures/ 2 样本），267 个 `def test_`；巨文件 test_memory_context.py（1792 行/41 测）+ test_m06_agent_tool_loop.py（1470 行/31 测）占近半数用例；`__pycache__` 残留已删 test_migration_v4.pyc。
- **命名过时**：7 个 test_m06_*（题面「8」实为 7）+ test_neo4j_graph_memory.py（内部 m05 命名 m05-g1-v1/M05_FOLLOWS，测 repo/neo4j/memory_graph.py）+ 行为/通用名文件（run_events/api/agent_loop…）；除 test_memory_evals.py（测仓库根 evals/memory/，非 venagent）与 test_test_configuration.py（测 conftest 自身）外，import 全部命中当前 venagent 路径，无坏 import。
- **conftest 极简**：唯一共享 fixture `neo4j_graph_store`（tests/conftest.py:66-94，仅 test_persistence.py:291/461 用；test_neo4j_graph_memory.py:218-228 自建 inline 同款）；导入期 env 注入（:21 setdefault VENAGENT_SANDBOX_DISABLED=1、:23 固定 VENAGENT_INVOCATION_ENCRYPTION_KEY、:13-63 TEST_DATABASE_URL/TEST_NEO4J_URI 从 .env 装配）；对象装配由各文件私有 helper 重复（_service/_tool_control/create_app 三套），无按模块 conftest。
- **fixtures/**：fake_mcp_server.py（92 行，test_m06_mcp.py:35 引用，保留）；responses_simulator.py（110 行，仅 scripts/run_responses_simulator.py:19 引用，测试面孤儿）；`.gitignore` 无 fixtures 条目（「未跟踪」说法与 .gitignore 现状不符）。
- **集成门控**：TEST_DATABASE_URL（test_persistence.py:65-67 skip）、TEST_NEO4J_URI（conftest:71 + neo4j_graph_memory:220 双份 inline skip+importorskip）、VENAGENT_RUN_DOCKER_INTEGRATION=1（test_m06_agent_tool_loop.py:1189/1238/1315 三个真 Docker，monkeypatch 反转 sandbox-disabled）、win32 skipif（test_m06_mcp.py:56）；pyproject.toml:35-37 仅 testpaths=["tests"]+pythonpath=["."]，**无 markers 注册、无 addopts**。
- **验证过载 10 实例（§6）**：① warn 审批→批准→resume 契约 4 处叠测（langgraph:32-76 / tools:383-507 / agent_tool_loop:369-460+584-703）；② 多工具被拒三连（agent_tool_loop:335/433/843）；③ approval 幂等拆两处（agent_tool_loop:1442-1470 vs persistence:61-79）；④ natural memory 双写（memory_integration:62-104 vs agent_loop:184-249）；⑤ G1 图语义 4 文件分层重复（memory_context:1065/1133/1207、graph_store:40-117、neo4j_graph_memory:143-194、memory_evals:60-93）；⑥ run lifecycle 3 文件重复（runs:38-275 / commit_recovery:79-218 / persistence:239+634+675+722+805）；⑦ 私有符号断言群：`runtime._tool_nodes`（agent_tool_loop:286、memory_integration:84）、`_answer_node`（agent_loop:173/238）、`_execute/_checkpointer`（commit_recovery:93/102/104/139/169/176/207）、`sandbox._existing_container/_containers/_container_generations`（agent_tool_loop:1233/1279/1306/1386/1397-1406）、`app.state.agent_runtime._worker_task`（api:240-241）、`control.project_tool_result`（agent_tool_loop:820/826）；⑧ 精确 SQL/Cypher 文本断言（memory_context:1483-1491 隔离级别/表名、migration:36-51 迁移 SQL 前缀+import 私有 _migrate_to_v5/v8/v9/v10、neo4j:156-193 归一化 Cypher）；⑨ 结构断言（test_package_layout.py:10-89 精确文件集合+`not (PACKAGE/"infra").exists()`、:151-167 `MemoryService.bases==[]`+文件行数≤800+协作类名 in content、agent_loop:47-58 `set(RunState.__annotations__)` 精确集合、startup_reporting:16 import 私有 bootstrap._health/_startup_report/_memory_capability_registry）；⑩ 元测试 test_test_configuration.py（import tests.conftest 测私有 loader）。
- **重写保留清单（§7）**：真实 Docker 3 件套骨架（agent_tool_loop:1189-1390 create/execute/cleanup、timeout/cancel 销毁、skill 只读物化 :1319-1390）；跨进程 state-directory lease（test_m06_persistence.py:150-183）；run tool snapshot 跨 restart（:186-249）；checkpoint 不保留 context_messages/secret 契约（agent_tool_loop:1040-1064）；fake_mcp_server.py；MCP 缓存失效 catalog_revision 单调（mcp:349-455）；skill digest/降级/rate-limit（skill_hub:88-226）；catalog allow/deny/availability 与降级 reason_code（tools:120/583-621）；HTTP control 面 owner 隔离（tools:786）；sandbox 惰性创建时序（agent_tool_loop:1005-1186）；PG restart 套件（persistence:239/634/675/722/805）；Neo4j round-trip（neo4j_graph_memory:218-231）。
- **其他**：gold 数据留在仓库根 `evals/memory/*.jsonl`（graph_gold_v1/store_policy_v1/timelines_v1/recall_gold_v1），tests/ 不复制；README.md:511「~50 个单元测试文件」与实 33 不符需修正；test_package_layout.py 断言以新目录树 draft 为改写源（map.md:33 已定）；tests/ 无 __init__.py，包路径导入依赖 pyproject pythonpath=["."] namespace 机制。

## Resolution（RESOLVED，10 项拍板 + 执行设计 + 验证方案，2025-07 用户逐块确认）

### 决策（D1-D10）

- **D1 归位映射**（按草稿确认）：30 测试文件 → 12 目录：tests/agent/（test_agent_loop 重写、test_commit_recovery、test_m06_agent_tool_loop 重写、test_m06_langgraph 审批契约并入、test_runs、test_conversation、test_run_events）、tests/tools/（test_m06_tools 重写、test_m06_persistence 整体归 tools）、tests/mcp/（test_m06_mcp）、tests/skills/（test_m06_skill_hub）、tests/memory/（test_memory_context 拆分、test_memory_index、test_memory_maintenance、test_memory_semantics、test_memory_graph_store、test_m06_memory_integration natural intent）、tests/repo/（test_persistence、test_migration、test_neo4j_graph_memory）、tests/llm/（test_llm）、tests/config/（test_config）、tests/http/（test_api、test_streaming_api、test_streaming）、tests/ownership/（test_ownership）、tests/platform/（test_startup_reporting）、tests/ 根（test_package_layout 重写、conftest、fixtures/）。
- **D2 清理范围**：M06 7 文件按保留清单重写（真实 Docker 3 件套骨架 agent_tool_loop:1189-1390、跨进程 state-directory lease persistence:150-183、run snapshot 跨 restart :186-249、checkpoint 不保留 context/secret :1040-1064、fake_mcp_server、MCP 缓存失效 catalog_revision 单调、skill digest/降级/rate-limit、catalog allow/deny/availability+reason_code、HTTP control owner 隔离、sandbox 惰性创建时序、PG restart 套件、Neo4j round-trip）；**非 M06 23 文件归位+重命名+拆巨文件+删重复断言，不重写**（保覆盖、控成本）。
- **D3 特殊件**：test_memory_evals.py 移出 tests/ 随仓库根 evals/ 走（evals 工具自带测试，目标包非 venagent）；test_test_configuration.py **删除**（conftest 装配逻辑改直接测 load_config 行为，不再元测试私有函数）；test_package_layout.py 留 tests/ 根重写为新树结构断言（只断言文件集合存在性，去 bases==[]/行数上限/源码字符串）；test_neo4j_graph_memory.py 改名 test_repo_neo4j_memory_graph.py（去 m05 命名）。
- **D4 fixtures**：responses_simulator.py **删除** + scripts/run_responses_simulator.py 一并删除（唯一消费者，模拟器已过时）；fake_mcp_server.py 随被测模块就近归 tests/mcp/fixtures/；fixtures/ 内统一放本地样本/假服务（无网络、无真实依赖）。
- **D5 conftest 拆分**：顶层 conftest 只留全进程级事实（env 注入 + TEST_* 装配 + skip 门控）；各 tests/<module>/conftest.py 收编本模块对象装配工厂（_service/_tool_control/create_app 三套去重）——工厂就近、门控集中。
- **D6 集成标记**：单一 `@pytest.mark.integration`（所有真 PG/Neo4j/Docker 测试）；pyproject 注册 markers；三套 env（TEST_DATABASE_URL / TEST_NEO4J_URI / VENAGENT_RUN_DOCKER_INTEGRATION）保留、语义收敛为「integration 测试缺对应 env 时 skip」；运行约定 README 文档化——默认 `pytest` 跑单元面+有 infra 自动跑集成，`pytest -m integration` 只跑集成面（缺 env 的 skip）；无命名后缀约定（不加 test_*_integration）。
- **D7-D10 验证过载治理五条规则**（G7 拍板）：①**同契约单点断言**——4 层叠测（warn 审批/多工具被拒/G1 语义/run lifecycle）只留一层，重写时选权威层（用户可观察行为=HTTP/服务层，机制层只测机制本身）；②**禁私有符号断言**——`_` 前缀（_tool_nodes/_answer_node/_execute/_checkpointer/_worker_task/_existing_container/_containers/project_tool_result）必须经公开接口断言；③**禁精确 SQL/Cypher 文本断言**——mock 仓储返回行→断言读取/写入行为结果（memory_context:1483-1491、migration:36-51、neo4j:156-193 均重写）；④**禁结构断言**——bases==[]/行数上限/源码字符串 in content（package_layout:151-167、agent_loop:47-58 RunState.__annotations__ 精确集合、startup_reporting:16 私有 import 均清理）；⑤**单文件 ≤600 行/一文件一职责域**——test_memory_context.py（1792 行）拆 6 主题（service/command_adapter/short_term/G1/quarantine/pg_mock），test_m06_agent_tool_loop.py（1470 行）重写时按契约域拆。
- **G8 模拟器连带**（并入 D4）：两文件一并删。
- **G9 marker 形态**（并入 D6）：单 marker + env 收敛 + -m 选择，不做子 marker 不做 env 单开关。

### 执行设计（实现时按此展开）

**阶段 1 目录与归位（机械性，先行）**：建 12 个 tests/<module>/ 目录；非 M06 23 文件按 D1 移动+改名（test_<主题>.py）；test_memory_evals.py 移 evals/；删 test_test_configuration.py、responses_simulator.py、scripts/run_responses_simulator.py、__pycache__ 残留（test_migration_v4.pyc）；fake_mcp_server.py 移 tests/mcp/fixtures/。

**阶段 2 非 M06 清理（归位保留，按五条规则）**：test_memory_context.py 拆 6 主题文件；各文件去私有符号断言（改公开接口断言或删）、去叠测（同契约单点）、去结构断言；文件尾私有 helper 工厂迁各模块 conftest（D5）；test_package_layout.py 重写为新树断言。

**阶段 3 M06 重写（归位+契约测试）**：tests/agent/（闭环/审批/恢复契约，含 test_m06_langgraph 审批并入 + test_m06_agent_tool_loop 重写 + test_agent_loop 重写）、tests/tools/（gateway/catalog/approval 契约 + test_m06_persistence 的 Operation/Approval/lease/snapshot）、tests/mcp/、tests/skills/；保留清单（D2）逐项落位；真实 Docker 3 件套与 PG restart 套件打 @pytest.mark.integration。

**阶段 4 配置与文档**：pyproject markers 注册（integration）；README.md:511「~50 个单元测试文件」修正为实际结构；README 运行约定更新（默认 pytest / pytest -m integration / 三 env 说明）；conftest 顶层+模块拆分完成。

### 验证方案（Resolve 标准）

1. 重组后默认 `pytest` 全量绿（单元面全过；有 infra env 的 integration 自动跑，无 env skip）。
2. M06 重写后等价覆盖基线：原 test_m06_tools=20 passed、test_m06_langgraph+test_m06_agent_tool_loop=31 passed+3 skipped 的契约在新归位文件中保留（审批/拒绝不执行/幂等/checkpoint 无 secret/跨进程 lease/run snapshot）。
3. `pytest -m integration` 在有 env 时跑集成面、缺 env 自动 skip 不报错。
4. 五条规则抽检：全仓 grep `runtime\._|_tool_nodes|_answer_node|_execute|_checkpointer|_worker_task|_containers|bases\s*==|splitlines\(\)\s*<=` 零命中（test_package_layout 新树断言除外）。
5. test_package_layout 断言与 tests/<module>/ 实际结构一致。
6. 无死引用：`responses_simulator`、`test_test_configuration`、`test_memory_evals` 相关 import 全仓清理干净。

### 明确不做的遗留

- 覆盖率门槛（roadmap 已定：不做全仓覆盖率）。
- 集成测试机制大改（保留 env 门控 + skip 语义，只加 marker 选择能力）。
- 测试全量重写（D2：非 M06 归位保留）。
- 引入新测试框架/插件（维持 pytest 现状）。