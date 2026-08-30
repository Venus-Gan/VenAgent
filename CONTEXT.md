# VenAgent

VenAgent 是 AGI-saber 的 Python 重构版：基于 LangChain/LangGraph 的自托管 AI 助手运行时，提供会话、记忆、受控工具执行（审批 + 沙箱）、RAG 检索与任务编排，经 FastAPI + Vue 3 暴露 Web 界面。项目用 Matt Pocock 的 Wayfinder 流程管理路线决策。

## Documentation

- `README.md` — 项目总览与目录树（新目录树见 `docs/wayfinder/assets/新目录树-draft.md` 定稿）
- `docs/roadmap.md` — 剩余功能路线（模块顺序 + 每模块完成标准 + 可靠 agent 验收）
- `docs/adr/` — 架构决策记录（难反转决策）
- `docs/reference/` — 研究参考（AGI-saber 行为对照等）
- `docs/wayfinder/` — Wayfinder tracker（map.md + tickets/ + assets/）

## Language

### 执行模型

**run**: 一次用户请求的完整执行实例，持有唯一 `run_id`。
_Avoid_: task, job

**conversation**: 按 run 归属的消息集合；无 PostgreSQL 时由内存驱动兜底，保证本地匿名对话与工具执行可用。

**checkpoint**: LangGraph 检查点，保存图恢复现场。恢复时重核授权，版本不兼容标记 `incompatible`；用户重试 = 新 run 新 checkpoint 链，不支持时间旅行。
_Avoid_: snapshot（快照只记录不自动恢复）

**M06 执行环**: 单工具闭环（prepare → model_decision → execute_tool → model_finalize → final），工具执行的唯一权威。
_Avoid_: tool loop 的其他叫法

**approval**: 工具执行前的人工审批（LangGraph interrupt）；中断恢复时重新核验授权。

**operation**: 一次工具调用的幂等身份（`operation_key`），用于副作用对账。
_Avoid_: tool call id（无幂等语义）

### 能力与降级

**capability registry**: 启动登记的能力注册表；依赖缺失标 `disabled`/`unavailable`，统一经 503 `persistence_unavailable` 暴露，不静默吞错。
_Avoid_: readiness 布尔、吞错降级

**repo adapters**: 数据边界实现（postgresql / neo4j / inmemory），只实现 ports，不承载业务事实。
_Avoid_: repository 泛称、双镜像

**bootstrap**: 组合根，全仓库唯一装配点。
_Avoid_: main wiring、factory

**platform**: 技术资源层（sandbox、容器、Milvus/ES 等基础设施驱动），不承载业务事实。
_Avoid_: infra（与业务事实混淆）

### 上下文与记忆

**ContextBlock**: 上下文装配单元；promptctx 把已授权候选按槽位预算投影为 ContextBlock。
_Avoid_: prompt string（暗示单一字符串）

**ContextProjection**: 每次模型调用前的纯投影；只投影能力，不授予权限，不承担恢复/审计/取消。
_Avoid_: prompt building（暗示权限）

**recall**: 长期记忆召回；每次 run 自动注入（recall → promptctx → ContextBlock），无手动"回忆"模式分支。
_Avoid_: memory retrieval 泛称

**沉淀（consolidation）**: 长期事实的异步批量写入：攒满 N 条用户消息或会话静默触发（先到先触发），窗口内多轮聚合成一次 LLM 抽取，经槽位合并落库。显式「记住/忘记」指令不走沉淀，保持同步即时写——「显式即时、隐式沉淀」双轨。
_Avoid_: 实时转写、每轮抽取、reflection（编排层语义）

### 编排

**Selector**: 编排层第一步的意图路由节点，隐性分发 ReAct / RAG / 直接回答三支；无前端开关、无手动模式选择。
_Avoid_: intent policy、router 泛称

**Planner / Replanner**: 计划层节点；Planner 产出计划，Replanner 事件驱动修订（节点失败 / 观察不足 / 依赖失效 / 前提改变）。
_Avoid_: task graph、static DAG（一次性死图）

**NodeOutcome**: 图节点结果，以稳定 identity 归并。
_Avoid_: step result（不稳定引用）

### 检索

**RAG**: 文档摄入 → 分块 → 三路召回（Milvus dense + ES BM25 + Neo4j 图）→ RRF 融合 → 可选 LLM rerank → small-to-big → 证据引用回答。
_Avoid_: vector search（单一检索）

**evidence**: RAG 回答引用的来源证据，与个人记忆分属不同 owner / TTL / 删除规则。

### 项目治理

**Wayfinder**: 项目决策流程：map.md 维护路线；tickets 记录决策（grilling 票须真人交互 resolve，research 票派子代理，产物存 assets/ 不提交 git）。
_Avoid_: comet、native change、spec/verify/archive 阶段

**src 包**: 形态 C（ADR-0010，2026-08-30 拍板）后唯一 Python 源包为 `src/`（由 `venagent/` 改名，包级改名）；import 一律 `src.*`。**venagent 仍是产品名**：pip 包名（pyproject name）保留 `venagent`，数据库表/库名、logger、JWT issuer、docker 标识、skills `compatible_runtimes`、localStorage/事件名等产品标识一律保留不变（禁止盲替换）。
_Avoid_: 根级多包（platform/mcp 遮蔽 stdlib 与 PyPI SDK）、`import agent`（src 必须是包，目录容器会重引遮蔽）

**mcp-configs 目录**: MCP 配置与运行时状态目录 `src/mcp/mcp-configs/`（含 `mcp-servers.json` 与 `state/`：approvals/operations/artifacts/invocations/run-tool-snapshots/skills/`venagent-state.lock`）；包锚定（`bootstrap.py` 以 `__file__` 解析，与 cwd 无关），gitignored。边界：非 editable 安装（site-packages）时不可写，项目属「仓库内运行」范式。
_Avoid_: 根 `mcp/`（已删除）、cwd 锚定

**AGI-saber**: 行为参考项目（Go 实现），是问题清单与风险样本，不是目录 / 表结构 / 驱动迁移模板（个别条目由 ADR-0006 明确推翻）。
_Avoid_: 迁移模板
