# AGI-saber 设计参考（VenAgent 行为对照）

> 本文由 docs/discussions/agi-saber-design-reference.md 按 docs 重建规范重写（原讨论已备份至 `.backup/`）。这是**研究参考**，不是 VenAgent 的运行规格、迁移方案或兼容承诺。AGI-saber 是问题清单与风险样本，不是目录/表结构模板——除 ADR-0006 明确批准迁移的条目外，Do-not-copy 边界仍然有效。

## 证据优先级

1. VenAgent 当前源码、`CONTEXT.md`、`docs/roadmap.md`、`docs/adr/` 与 Wayfinder 已结案票，决定真实边界。
2. 本机 AGI-saber 静态代码与架构文档（`D:\VSCProject\AGI-saber`，Go 工作副本 `fead7687a82965b3c0106728089ccde0cc0eb3e8`），核对实际行为、接口、依赖、测试与风险。
3. AGI-saber 语雀文章（访问时间 2026-08-04），解释设计动机与演进过程；文章愿景不自动等于已实现行为。

## 一页结论

AGI-saber 的核心是一条能力组合链：

```text
用户请求
  -> 复杂度路由（chat / tool / RAG / ReAct）
  -> Context/Memory 装配
  -> Tool 或 RAG 执行
  -> Planner / TaskGraph / Replanner
  -> 并发、竞速、重试、快照与事件推送
  -> Generator / Finalizer 输出
```

六个稳定思想：

- 简单请求走短路径，复杂任务才进入图执行。
- Prompt 不是单一字符串，而是按槽位与预算装配的上下文。
- 记忆按生命周期和用途分层，任务观察不污染长期记忆。
- RAG 不是单一向量库，而是摄入、分块、多路召回、融合、重排和可追溯回答的流水线。
- 工具是受控的本地能力：描述可交给模型，执行按钮与安全策略留在系统侧。
- 外部依赖可以缺席，但缺席必须被标记、降级或阻断，不能伪装成成功。

## 主题到 VenAgent 模块

| AGI-saber 主题 | VenAgent 对应 | 设计输入 | 明确不做 |
|---|---|---|---|
| 身份、文档、记忆访问、删除、健康与降级 | ownership（已实现） | 所有权过滤、撤销/删除顺序、依赖状态对用户可见 | 全局文档/全量记忆查询接口 |
| STM、Preference、LTM、GraphMemory、promptctx | memory + promptctx（已实现，重构落地在路线第 4 步） | 记忆候选、来源、分类、召回、TTL、冲突、治理、上下文预算 | 把 Prompt/TaskMem 变成长期记忆权威 |
| Tool、MCP、Skill、sandbox、取消、审计 | M06 tool-execution（已实现，基线） | 工具注册边界、执行授权、审批、沙箱、幂等、副作用对账 | 未经审批的通用命令执行、全局 MCP 注册 |
| Router、Planner、TaskGraph、Replanner、子 Agent、快照 | M07 agent-orchestration（路线第 6 步） | 图节点边界、并发/竞速、恢复、计划修订、子 Agent 输入输出 | 迁移旧 TaskState、把图现场放进业务 State |
| 文档、父子块、Dense/BM25/图检索、RRF、rerank、evidence | M08 rag（路线第 3 步） | 文档生命周期、引用、检索降级、索引一致性、评测 | 把 RAG 混成个人记忆 |
| 配置、可选依赖、事件总线、状态、日志、备份恢复 | platform（已实现） | readiness、启动报告、失败策略、审计 | 因旧项目存在就预建 queue/scheduler/operator 面板 |

## 复杂度路由

事实：语雀与 Go 代码都把运行模式分成纯对话、RAG、单工具、ReAct，且复合推理优先于单工具、单工具优先于纯 RAG；`runtime_process.go` 有统一的 prepare → dispatch → finalize 链路。两个入口：前端显式勾选工具直接进工具路径；未显式选择时用快速规则判断天气/时间/搜索/知识库意图。

取舍（VenAgent 已定，见 ADR-0007）：Selector 隐性分发三支（ReAct / RAG / 直接回答），规则+模型判断组合，无前端开关。**Do-not-copy**：不把关键词命中、前端勾选或 Prompt 中的工具描述当作授权；关键词路由不能成为最终业务事实。

## 从 Static DAG 到 Plan-and-ReAct

事实：早期实现是 Static DAG（Planner 一次输出全图，Executor 按拓扑层执行，无中途 LLM 决策）；后续引入 Replanner——每层完成或节点失败后结合图快照与 observations 判断，返回空数组表示观察足够，需要时只追加增量节点，新节点可依赖已完成节点并在下一轮进入 ReadyNodes。代码对应 `plan_graph.go`、`graph.go`、`runtime_graph.go`、`replanner.go`，支持拓扑层并发、`race_group` 首成功、节点重试、超时、SSE 事件、任务快照。

设计意图：真正的 ReAct 是"观察改变后续行动"；计划可据中间事实修订，节点状态/依赖/重试/恢复由图运行时统一管理。

代价与风险：Replanner 增加模型调用与成本；动态加节点需要稳定 ID、依赖校验、循环检测、幂等恢复；"首成功"适合互斥候选但不适合已产生外部副作用的工具；旧实现 map 遍历、宽锁、失败节点保留造成顺序不稳定或审计与真实图不一致。

取舍（ADR-0005）：Planner/Executor/Replanner 职责拆分与节点级 retryable/error code 已采纳；用 LangGraph 公开 State/interrupt/checkpoint/reducer；M06 工具事实与 M07 图现场分开。**Do-not-copy**：不迁移 Go TaskGraph/TaskState/SSE 字段/硬编码 agent 名称。

## 记忆与 Context：按用途与生命周期分层

五种形态：ShortTerm（最近对话窗口，进程/会话）、Preference（结构化属性，跨会话）、LongTerm（可语义召回的事实，长期可衰减，Embedding + TF 兜底）、GraphMemory（关系与间接联想，1-hop 扩展）、TaskMemBuffer（任务步骤观察，最近 K 环形缓冲）。Promptctx 把来源映射到有预算的槽位；身份/约束/profile 不与普通 episodic recall 竞争 Top-K；任务步骤不在任务结束后污染长期记忆。

写入链路：用户消息/回复 → 规则或 LLM 抽取候选 → poison gate → 分类 → embedding/TF → 去重/隐式合并 → 写入。召回按用途分流（profile 按类别、recall 用向量+TF 降级混合 importance、graph 有限邻居扩展、task 最近 K）。合并含衰减、去重、冲突/替代、TTL 淘汰；"双门槛过期"：足够老且重要性足够低才淘汰。

风险（Go 代码）：`longterm.Consolidate` 跨用户字段约束与 GraphMemory UserID 传播需加强；图扩展召回必须重查 owner/quarantine/superseded/TTL/敏感性；HTTP 层返回全量 LTM 或把过滤交给前端是 ownership 反例。

取舍：分层、来源/分类/TTL/冲突/审计作为领域事实已采纳；VenAgent 的 owner/RunGrant/删除与 privacy 规则约束召回；LangGraph checkpoint 保存图恢复现场而非长期记忆。**Do-not-copy**：不复制 Neo4j schema、具体阈值、"前端过滤全量记忆"接口。

## RAG：从文档摄入到有来源的回答

链路：文档清洗 → 标题感知/递归切分 → Embedding；用户问题 → Query 理解/改写 → 多路检索 → Rerank → Prompt 组装 → LLM 回答。偏好：Markdown 保留标题/列表/表格/代码块；长 section 递归切分小重叠；child chunk 精准召回、parent context 恢复语义；Dense 擅长语义与同义、BM25 擅长 API 名/版本号/错误码/专有名词；必要时叠加 Neo4j 图检索，RRF 融合后 rerank + small-to-big 回填。Go 代码 `domain/rag` + `infrastructure/persistence/ragchunk`：PG 保存原文与 embedding 为可恢复真相源，ES/Milvus/Neo4j 是增强索引或图层，缺失时可降级 semantic/keyword/unavailable。

设计意图：RAG 减少三类错误——资料不在模型参数中、精确词与语义互相漏召回、命中的小块缺乏生成上下文与来源。

代价与风险：三路系统的索引一致性与运维复杂度；PG 删除成功而 ES/Milvus 失败产生孤儿索引（无 outbox/reconciliation 不能宣称彻底删除）；多 query 融合以正文为唯一聚合 key 可能错误合并；PDF 外部命令/临时文件/图谱抽取需独立路径、大小、超时与沙箱边界；RAG evidence 与个人记忆 owner/TTL/来源/删除规则不同，不能共用一个"上下文池"。

取舍（ADR-0006）：父子块、混合检索、query rewrite、rerank、来源追踪、"真相源+增强索引"分层已采纳；驱动与固定 RRF 权重**已批准迁移**（用户推翻原 Do-not-copy 条目，见 ADR-0006）；Evidence 与引用为领域事实，按当前授权重新检索。**Do-not-copy**（仍有效）：不迁移 SQL 表、删除顺序；不把 RAG 当作 Prompt 中无来源文本。

## Tool、MCP、Skill 与 Sandbox

工具抽象："名片 + 按钮"——Name/Description/Parameters 给 LLM 看，Execute 是系统本地按钮不可序列化给模型。注册表读写锁 + snapshot 无锁遍历长任务，避免动态注册阻塞 ReAct。自实现 JSON 风格解析（非 provider 原生 function calling）用多层防线处理不稳定输出：Prompt 约束、代码块清洗、多 schema 解析、白名单过滤、规则降级、DAG 环检测。

Sandbox：Validator → Block/Warn → Executor → Audit；Docker/Local/Mock 后端，命令长度、风险级别、资源限制、网络、文件系统与超时由策略控制。MCP 需要超时、状态码、重试、SSRF、owner、审批、审计边界。

风险（Go 代码）：MCP 全局注册、`context.Background()` 固定超时、本机执行参数复用错误、异步审计缺少完整身份，均不可迁移。

取舍（ADR-0003）：工具描述与执行分离、结构化错误、snapshot 减少长锁、sandbox 校验/执行/审计分层已采纳；M06 使用 RunGrant/OperationGrant/ApprovalItem/credential broker/幂等 operation identity，执行前再次授权；M07 只选择与编排，M06 持有工具/审批/沙箱/副作用事实。**Do-not-copy**：不允许用户输入直接注册全局 MCP endpoint、不把 JSON Prompt 解析结果视为授权、不复制旧版命令执行与路径配置。

## 子 Agent、文档库与长任务

AGI-saber 将 research/writer/review/doc 子 Agent 组织为注册表与固定任务链（research → writer → review → doc）；长任务经 TaskGraph/TaskState/快照/SSE/取消对外呈现；图节点持短观察与稳定引用，Generator 合成答案。价值：隔离职责、输出契约与失败边界，与 Replanner 结合可先调查再补步骤。

取舍：显式子 Agent 输入/输出契约与任务级进度已采纳；M07 通过 LangGraph 子图/受控 subgraph 管理恢复；最终回答、文档 artifact、evidence 与 AgentRun 分开建模；前端显示关联状态而非把中间文本伪装成正式消息。**Do-not-copy**：不把硬编码子 Agent 名称、共享全局 Agent 或本地文件写入当作通用能力。

## 平台、降级与观测

AGI-saber 启动时分别连接 PostgreSQL/Milvus/Elasticsearch/Kafka/Neo4j/sandbox，允许部分缺失以降级模式运行；配置按 Server/LLM/Storage/RAG/Memory/Harness/Sandbox/Security/Graph/Auth/Observability 分组，严格 YAML 解析与 env 展开；并行 bootstrap、统一 `/api/status`、结构化日志、Compose healthcheck、优雅关闭。

必须保留的反例：`/readyz` 恒 200 不能证明依赖 readiness；InfraStatus 是启动快照不反映后续故障；Kafka 写失败只记日志（无 outbox/持久重试/对账）；PG DDL 逐条执行且错误只告警（半升级风险）；Compose 含开发凭据与外网暴露不能当生产模板；无平台级备份/灾备，任务快照 ≠ 数据库恢复方案。

取舍（ADR-0001）：能力分组配置、严格字段校验、结构化日志、启动报告、显式降级状态（capability registry disabled/unavailable + 统一 503）已采纳；LangSmith trace、LangGraph checkpoint、AgentRun 状态、M06 审计与平台指标分开观察并用稳定 ID 关联。**Do-not-copy**：不把"依赖可选"理解为"依赖失败也返回成功"、不把任务快照称作灾备、不提前创建 queue/scheduler。

## 总体决策

| 决策 | 内容 |
|---|---|
| Adopt | 复杂度路由、职责分层、Context 槽位、记忆生命周期、混合 RAG、工具描述/执行分离、sandbox 分层、可验证降级 |
| Extend | 用 owner、RunGrant、OperationGrant、Evidence、AgentRun、LangGraph checkpoint、ContextProjection 重建旧思想 |
| Compose | ownership 所有权 + memory/recall 事实 + M06 执行授权 + M07 图编排 + platform 平台证据 |
| Do-not-copy | 全局 Agent、隐式 Prompt、关键词作为授权、旧 TaskState、私有 checkpoint 表、未审批命令、前端过滤全量数据、无对账删除（Milvus/ES 驱动与 RRF 权重条目被 ADR-0006 推翻） |
| Build only when needed | 新调度器、分布式队列、operator surface、复杂图数据库能力、平台灾备系统 |

VenAgent 已确认的边界：`ConversationMessage`、`AgentRun`、LangGraph State、ContextProjection 与 M06 工具事实互不替代；`thread_id=run_id` 只是 adapter 映射（ADR-0004）；Prompt 只做本次调用的投影，不授予权限、不承担恢复/审计/取消；未实现能力用 absent/unavailable 表达，不创建空 provider。

## 路线模块的规划问题清单

- **memory/promptctx 重构**：哪些消息有资格抽取长期记忆？poison/来源/敏感信息过滤？recall/profile/task 如何竞争预算？conflict/quarantine/superseded/TTL/删除如何审计？
- **M06 多工具**：approval 是批量还是逐项？interrupt 恢复重跑如何保持幂等？未知工具结果、取消竞态、SSRF、路径与命令边界如何 fail closed？
- **M08 RAG**：文档版本、chunk、index、evidence、citation 如何归属与删除？召回失败/rerank 不可用/无结果/evidence-required 节点分别如何处理？PG 真相源与增强索引如何通过 reconciliation 证明一致？
- **M07 编排**：Planner/Replanner/Executor 输入输出契约？State 只保存哪些恢复所需引用？并行、竞速、重试、动态节点与 contract mismatch 如何验证？

## 来源与 Provenance

- 语雀设计材料（访问 2026-08-04，仅研究输入）：架构总览、从 Static DAG 到 Plan-and-ReAct、记忆系统详细介绍、RAG、Saber 工具调用全流程。
- 本机静态证据：`D:\VSCProject\AGI-saber`，重点 `internal/application/chat`、`internal/domain/{memory,rag,promptctx,tool,sandbox}`、`internal/infrastructure`、`docs/architecture/ARCHITECTURE_MAP.md`。冻结的 Python 参考提交 `2b995cdd8b2fb413bfb34c41456ec0bda92e6c2a` 仅作静态行为线索。
- 原讨论文档备份于 `.backup/discussions/agi-saber-design-reference.md`。
