# AGI-saber 全仓库重构审计与执行结论

> 研究目标：参考 Phase1 目标，先做全仓库重构审计，再沉淀成可以直接执行的迁移计划。
>
> 研究方法：优先使用本地 skill / agent / rules 面，再结合仓库源码、测试、Phase1 设计文档和官方文档进行交叉验证。

## 结论摘要

这次研究足以支撑 AGI-saber 的全仓库重构计划，但不支撑一次性推倒重写。

最合理的路线是：

1. 先处理安全与配置问题
2. 再抽出策略层、工具边界和运行时边界
3. 然后把自研图执行迁移到 LangGraph
4. 最后把固定子代理、工具注册和兼容层收口

Phase1 的方向是可行的，但必须按“渐进迁移 + 可回滚 + 测试门禁”来做。

---

## 研究范围

### 本地方法论

优先读过并采用的本地 skill：

- `search-first`
- `agent-architecture-audit`
- `workspace-surface-audit`
- `ecosystem-primer`
- `langchain-dependencies`
- `langchain-fundamentals`
- `langgraph-fundamentals`
- `langgraph-persistence`
- `langgraph-human-in-the-loop`
- `backend-patterns`
- `coding-standards`
- `tdd-workflow`

### 仓库 surface

- 当前 AGI-saber 代码位于 `/home/ubuntu/AGI-saber/final/`
- 仓库没有 `.agents/`、`.codex/` 工作流目录
- 仓库只有 `.claude/settings.json` 和 `.claude/settings.local.json`
- 现有测试集中在 `final/tests/`
- Phase1 目标文档位于 `/home/ubuntu/VenAgent/VibeCoding/Phase1/`

---

## 关键发现

### 1. 这是一个“自研中枢过重”的 agent 项目

`UnifiedAgent` 仍然承担了初始化、记忆、RAG、工具、子代理、promptctx、快照、路由和 ReAct 执行等多种职责。

相关证据：

- [`final/internal/agent/agent.py`](../final/internal/agent/agent.py)
- 初始化阶段同时装配 LLM、STM/LTM、Preference、RAG、ToolExecutor、subagents、sandbox、KG、promptctx
- `_prepare()` 里仍然做模式判断和上下文装配
- `_dispatch_mode()` 里继续分发 chat / rag / tool / react
- `_run_react_with_tools()` 里继续手写任务图、执行器和最终总结

结论：

- `UnifiedAgent` 现在不是“单一协调器”，而是“应用总装机”。
- 如果不先拆边界，LangGraph 迁移会被旧代码不断反向拉回去。

### 2. 图执行仍然是自研线程模型，不是 LangGraph

`GraphRuntime` 负责拓扑层执行、同层并发、race group、重试、取消、快照和子代理执行。

相关证据：

- [`final/internal/agent/graph_runtime.py`](../final/internal/agent/graph_runtime.py)
- `execute()` 使用 `topological_levels()`
- `_execute_group()` 和 `_race_group()` 自己管理线程与竞速
- `_execute_single_node()` 自己管理重试与状态写回
- `_execute_subagent_node()` 直接把任务交给注册表中的子代理

结论：

- 这个模块本质上是 LangGraph 想接管的工作。
- 现在的实现可以作为过渡层，但不适合作为最终编排层。

### 3. 工具边界还没有真正 MCP 化

当前工具系统仍然是“本地工具 + 手工降级链 + 动态注册”的模式。

相关证据：

- [`final/internal/tools/tools.py`](../final/internal/tools/tools.py)
- `search_web_factory()` 仍然是 Tavily -> LLM -> mock
- `build_tavily_tool()` 仍然会额外暴露 `tavily`
- `default_tools()` 会按配置拼装工具
- `new_mcp_tool()` 只是一个 HTTP 包装器，不是完整的统一工具协议层

结论：

- Phase1 要的不是“再加一层别名”，而是把外部能力收口成标准边界。
- 当前工具层适合先包起来，再逐步替换后端实现。

### 4. 路由还是关键词启发式

当前模式选择仍然依赖 `router.py` 的关键词规则。

相关证据：

- [`final/internal/agent/router.py`](../final/internal/agent/router.py)
- `need_tool()`
- `need_rag()`
- `need_react()`
- `detect_tool()`

结论：

- 这很适合早期原型，不适合 Phase1 的目标架构。
- 应该抽成一个可版本化、可审计、可回退的 `IntentPolicy`。

### 5. 子代理是固定注册，不是可扩展 preset 体系

当前子代理链路是固定的 research / writer / review / doc 四件套。

相关证据：

- [`final/internal/agent/subagents.py`](../final/internal/agent/subagents.py)
- `register_builtin_subagents()` 固定注册四个 agent
- `GraphRuntime` 通过 registry 直接取 `subagent.run(task)`

结论：

- 这和 Phase1 里 `agentteam/presets` 的方向一致，但实现还停留在固定内置级别。
- 适合先迁移注册表，再拆分为可复用 preset。

### 6. 配置系统存在严重安全问题

默认配置文件里存在硬编码凭据和密码。

相关证据：

- [`final/config/config.yaml`](../final/config/config.yaml)
- [`final/config/config.py`](../final/config/config.py)

结论：

- 这是重构前必须先修的阻塞项。
- 任何计划都必须包含：移除默认密钥、改用环境变量或本地覆盖文件、做密钥轮换、加扫描门禁。

### 7. 测试基础不错，但还缺少迁移级门禁

当前测试覆盖了配置、RAG、记忆、promptctx、图执行、文档、工具并发、前端契约等关键面。

相关证据：

- [`docs/项目导读/11-测试体系与验证方法.md`](../docs/项目导读/11-测试体系与验证方法.md)
- [`final/tests/`](../final/tests/)

缺口：

- 没有浏览器级 E2E
- 没有 LangGraph checkpoint / resume 专项测试
- 没有专门验证 `IntentPolicy` 的测试
- 没有明确的“迁移后兼容性”门禁

结论：

- 这个项目适合 TDD 驱动的重构。
- 迁移计划必须以测试分层来约束，不然会很容易回退到旧耦合。

---

## Phase1 对齐判断

Phase1 的目标方向是正确的，且可以落地为以下边界：

| 目标边界 | 当前状态 | 结论 |
|---|---|---|
| Core | RAG / memory / document / sandbox / infra 已存在 | 保留 |
| MCP | 只有轻量 HTTP 包装器 | 需要补强 |
| Graph | 仍是自研线程 runtime | 需要替换 |
| AgentTeam | 固定子代理 registry | 需要演进 |
| IntentPolicy | 不存在独立层 | 需要新增 |
| 配置与启动 | 仍是 YAML + main.py 直装配 | 需要重构 |

---

## 建议的重构顺序

### Phase 0: 安全与配置修复

目标：

- 移除默认配置中的硬编码密钥
- 把敏感项改为环境变量 / `config.local.yaml`
- 增加配置加载与密钥扫描测试

验收：

- 默认仓库配置不含秘密
- 应用可通过 env + local overlay 正常启动

### Phase 1: 边界抽取

目标：

- 新增 `intent_policy`
- 新增 `mcp`
- 新增 `agentteam`
- 新增 `runtime` 与 `workflow` 壳层
- 先做兼容 façade，不动外部 API

验收：

- 旧接口仍可用
- 新层能产出结构化决策
- 路由不再散在 `UnifiedAgent._prepare()` 里

### Phase 2: LangGraph 落地

目标：

- 用 `StateGraph` 表达状态、路由、并行、恢复
- 用 `checkpointer` 保存线程级状态
- 用 `interrupt()` / `Command(resume=...)` 表达 HITL 和恢复点

验收：

- chat / rag / tool / react 都能映射到图执行
- 恢复路径可回放、可回退

### Phase 3: 工具与 MCP 迁移

目标：

- 把外部能力统一包成 MCP 边界
- 替换 `search_web` 的 Tavily 主路径
- 保留 `exec_command` 的沙箱边界，但把高风险动作纳入显式门禁

验收：

- 上层只依赖标准化工具契约
- 不再把搜索后端写死在工具里

### Phase 4: agentteam/presets 迁移

目标：

- 把 research / writer / review / doc 工作流迁到 `agentteam/presets`
- 将固定子代理改成可扩展 preset 注册

验收：

- 文档型 workflow 不再依赖固定内置实现
- 预制子代理可以独立复用和扩展

### Phase 5: 清理与硬化

目标：

- 移除 legacy router/runtime/shim 依赖
- 补浏览器 E2E
- 补 checkpoint / resume 回归测试
- 把迁移门禁写进 CI

验收：

- 旧路径不再作为主入口
- 新架构稳定、可回滚、可验证

---

## 保留 / 替换 / 删除清单

### 保留

- RAG 底座
- memory 底座
- document 底座
- sandbox 底座
- infra / repo 层
- HTTP API 与 frontend 的外部契约

### 包装后保留

- 当前工具定义
- 当前子代理实现
- 当前快照 / 取消 / 恢复逻辑

### 替换

- 关键词路由 -> `IntentPolicy`
- 自研 `GraphRuntime` -> LangGraph
- 工具后端手工降级 -> 标准化工具边界
- `main.py` 直装配 -> bootstrap / config 分层

### 删除

- 默认配置中的硬编码凭据
- Tavily 作为默认主路径的设计
- 把业务实现直接暴露给上层的耦合点

---

## 风险与回滚

### 主要风险

1. 重构过程中同时改太多层，导致无法定位问题
2. 新图执行和旧 runtime 双轨并存时，状态语义不一致
3. 工具边界不稳定时，上层 agent 的行为会漂移
4. 配置迁移时误删旧字段，影响启动

### 回滚原则

- 每个阶段都保留兼容 façade
- 先加测试再移除旧路径
- 先验证新路径可用，再切默认入口
- 所有敏感配置变更先做本地验证，再推广到默认模板

---

## 参考证据

### Phase1 目标文档

- [`VibeCoding/Phase1/00_重构总览.md`](../VibeCoding/Phase1/00_重构总览.md)
- [`VibeCoding/Phase1/01_模块映射.md`](../VibeCoding/Phase1/01_模块映射.md)
- [`VibeCoding/Phase1/07_LangGraph落点.md`](../VibeCoding/Phase1/07_LangGraph落点.md)
- [`VibeCoding/Phase1/10_运行策略层.md`](../VibeCoding/Phase1/10_运行策略层.md)
- [`VibeCoding/Phase1/11_主agent与运行入口.md`](../VibeCoding/Phase1/11_主agent与运行入口.md)
- [`VibeCoding/Phase1/12_工具系统与执行器.md`](../VibeCoding/Phase1/12_工具系统与执行器.md)

### 当前实现

- [`final/internal/agent/agent.py`](../final/internal/agent/agent.py)
- [`final/internal/agent/graph_runtime.py`](../final/internal/agent/graph_runtime.py)
- [`final/internal/agent/router.py`](../final/internal/agent/router.py)
- [`final/internal/agent/subagents.py`](../final/internal/agent/subagents.py)
- [`final/internal/tools/tools.py`](../final/internal/tools/tools.py)
- [`final/config/config.py`](../final/config/config.py)
- [`final/config/config.yaml`](../final/config/config.yaml)
- [`final/main.py`](../final/main.py)

### 测试与导读

- [`docs/项目导读/11-测试体系与验证方法.md`](../docs/项目导读/11-测试体系与验证方法.md)
- [`final/tests/`](../final/tests/)

