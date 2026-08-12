# AGI-saber 设计思路与 VenAgent 模块路由参考

## 0. 文档定位

这是一份研究参考，不是 VenAgent 的运行规格、迁移方案或兼容承诺。

阅读时使用下面的证据优先级：

1. VenAgent 当前 `docs/comet/specs/`、`AGENTS.md` 和已确认的 Native 规格，决定 VenAgent 的真实边界。
2. 本机 AGI-saber 静态代码和架构文档，用于核对实际行为、接口、依赖、测试和风险。
3. AGI-Core 语雀文章，用于解释设计动机、演进过程和作者希望解决的问题；文章中的愿景不自动等于已实现行为。

本文按“事实 → 设计意图 → 代价与风险 → VenAgent 取舍”的顺序组织，并在每章标注 M04--M09 路由归属。

## 1. 一页结论

AGI-saber 的核心不是某一个模型、数据库或 Agent 框架，而是一条能力组合链：

```text
用户请求
  -> 复杂度路由（chat / tool / RAG / ReAct）
  -> Context/Memory 装配
  -> Tool 或 RAG 执行
  -> Planner / TaskGraph / Replanner
  -> 并发、竞速、重试、快照与事件推送
  -> Generator / Finalizer 输出
```

这条链路背后有六个稳定思想：

- 简单请求走短路径，复杂任务才进入图执行。
- Prompt 不是单一字符串，而是由不同来源按槽位和预算装配的上下文。
- 记忆按生命周期和用途分层，任务观察不应污染长期记忆。
- RAG 不是单一向量库，而是摄入、分块、多路召回、融合、重排和可追溯回答的流水线。
- 工具是受控的本地能力，工具描述可以交给模型，但执行按钮和安全策略必须留在系统侧。
- 外部依赖可以缺席，但缺席必须被标记、降级或阻断，不能伪装成成功。

对 VenAgent 最重要的启示是：可以借鉴这些问题分解和边界意识，但不能复制 AGI-saber 的全局 Agent、隐式 Prompt 拼装、旧版任务状态、私有持久化表或未经过 owner/审批约束的副作用执行。

## 2. AGI-saber 主题到 VenAgent 模块

| AGI-saber 主题 | VenAgent 模块 | 可进入 Shape 的设计输入 | 明确不提前创建 |
|---|---|---|---|
| 身份、文档、记忆访问、删除、健康与降级 | M04 `ownership-lifecycle` | 所有权过滤、撤销/删除顺序、依赖状态对用户的可见性 | 全局文档或全量记忆查询接口 |
| STM、Preference、LTM、GraphMemory、TaskMem、promptctx | M05 `memory-system` | 记忆候选、来源、分类、召回、TTL、冲突、治理和上下文预算 | 把 Prompt 或 TaskMem 变成长期记忆权威 |
| Tool、MCP、Skill、sandbox、取消、审计 | M06 `tool-execution` | 工具注册边界、执行授权、审批、沙箱、幂等、副作用对账 | 未经审批的通用命令执行或全局 MCP 注册 |
| Router、Planner、TaskGraph、Replanner、子 Agent、快照 | M07 `agent-orchestration` | 图节点边界、并发/竞速、恢复、计划修订、子 Agent 输入输出 | 直接迁移旧 TaskState 或把图现场放进业务 State |
| 文档、父子块、Dense/BM25/图检索、RRF、rerank、evidence | M08 `rag` | 文档生命周期、引用、检索降级、索引一致性和评测 | 迁移 Milvus/ES/Neo4j 表结构或把 RAG 混成个人记忆 |
| 配置、可选依赖、事件总线、状态、日志、备份恢复 | M09 `platform-governance` | readiness、启动报告、失败策略、审计、备份和恢复证据 | 因存在旧项目就预建 queue、scheduler 或 operator 面板 |

跨模块主线是：

```text
M04 身份与所有权
  -> M05/M08 提供记忆与 evidence 候选
  -> M06 管理工具与执行授权
  -> M07 编排计划、观察和恢复
  -> M09 提供可观测、降级和平台级治理
```

这只是依赖关系说明，不改变每个模块的领域所有权。

## 3. 复杂度路由：先选择运行路径

### 3.1 观察到的事实

语雀“架构总览”和“Saber 工具调用全流程”都把运行模式分成纯对话、RAG、单工具和 ReAct。工具文章明确给出一个优先级：复合推理优先于单工具，单工具优先于纯 RAG，纯 RAG 最后才处理知识库问答。当前 Go 代码的 `runtime_process.go` 也存在统一的 `prepare -> dispatch -> finalize` 链路和 `react/rag/rag_agent` 分发。

路由有两个入口：

- 前端显式勾选工具时，直接进入工具/React 路径。
- 未显式选择时，用快速规则判断天气、时间、搜索、知识库等意图。

### 3.2 设计意图

路由的目标不是让 LLM 决定一切，而是用低成本、确定性的入口把请求送到合适的运行时：

- 简单对话不承担 Planner 和图调度开销。
- 明确的单步工具任务不必构建完整 DAG。
- 复杂任务进入 Planner，RAG 作为工具参与，而不是抢占整个运行模式。
- 路由失败时仍有内部降级路径，不因一次分类错误直接让请求失败。

### 3.3 代价与风险

关键词路由便宜、快速，但不能成为最终业务事实。复杂表达、跨域请求和权限差异都会让关键词判断失真。若路由发生在身份和授权之前，错误模式还可能把不该读取的 memory、document 或 tool 暴露给后续节点。

### 3.4 VenAgent 取舍

- **Adopt**：保留“简单路径与复杂路径分离”的成本意识。
- **Extend**：路由输入必须包含已验证的用户、run、能力和权限事实。
- **Compose**：把路由结果映射到 LangGraph 的公开 graph contract，而不是生成第二套任务状态。
- **Do-not-copy**：不把关键词命中、前端勾选或 Prompt 中的工具描述当作授权。

路由 Shape 问题：路由失败是继续走保守路径、返回澄清、还是结构化失败？哪些能力缺失可以降级，哪些能力缺失必须 fail closed？

## 4. 从 Static DAG 到 Plan-and-ReAct

### 4.1 观察到的事实

语雀“从 Static DAG 到 Plan-and-ReAct”明确承认早期实现更接近 Static DAG Plan-and-Execute：Planner 一次输出全图，Executor 按拓扑层执行，Generator 一次合成答案，中途没有 LLM 决策。

后续引入 Replanner：

- 每层执行完成或节点失败后，结合当前图快照和 observations 再判断。
- 返回空数组表示观察已经足够。
- 需要更多信息时只追加增量节点。
- 新节点可以依赖已经完成的节点，并在下一轮立即进入 ReadyNodes。
- 动态节点沿用同一套状态机和图校验。

本机代码中对应 `plan_graph.go`、`graph.go`、`runtime_graph.go` 和 `replanner.go`。当前实现还支持拓扑层并发、`race_group` 首成功、节点重试、超时、SSE 事件和任务快照。

### 4.2 设计意图

真正的 ReAct 不只是“调用多个工具”，而是让观察改变后续行动：

```text
规划 -> 执行 -> 观察 -> 判断是否足够
                         |-- 足够：生成答案
                         |-- 不足：追加节点 -> 继续执行
```

这带来两个工程收益：

- 计划可以根据中间事实修订，而不是把所有不确定性提前编码进一张死图。
- 节点状态、依赖、重试和恢复仍由图运行时统一管理，不必为每种新工具写一套循环。

### 4.3 代价与风险

- Replanner 增加模型调用、延迟和成本。
- 动态加节点需要稳定 ID、依赖校验、循环检测和幂等恢复。
- “首成功”适合互斥候选，但不适合已经产生外部副作用的工具。
- 旧实现的 map 遍历、宽锁、失败节点保留等细节可能造成顺序不稳定、阻塞或审计状态与真实图不一致。

### 4.4 VenAgent 取舍

- **Adopt**：Planner、Executor、Observation、Replanner 的职责拆分，以及节点级 retryable/error code。
- **Extend**：使用 LangGraph 的公开 State、interrupt、checkpoint 和 reducer；将 M06 的工具事实与 M07 的图现场分开。
- **Compose**：把 ContextProjection 作为每次模型调用前的纯投影，把 Replanner 输入限制为授权后的当前观察和稳定引用。
- **Do-not-copy**：不把 AGI-saber 的 Go TaskGraph、TaskState、SSE 字段或硬编码 agent 名称直接变成 VenAgent API。

M07 Shape 至少要回答：计划修订的边界是什么？节点重放时如何避免重复副作用？动态节点和 checkpoint 的 contract 如何版本化？

## 5. 记忆与 Context：按用途和生命周期分层

### 5.1 五种记忆形态

语雀“记忆系统详细介绍”和本机 `internal/domain/memory`、`internal/domain/promptctx` 共同呈现了五种形态：

| 形态 | 主要用途 | 生命周期 | 典型召回 |
|---|---|---|---|
| ShortTerm | 最近对话窗口 | 进程/会话 | 固定窗口 |
| Preference | 姓名、偏好等结构化属性 | 跨会话 | 按字段或类别 |
| LongTerm | 可语义召回的事实和事件 | 长期、可衰减 | Embedding，TF 兜底 |
| GraphMemory | 记忆之间的关系与间接联想 | 长期 | 1-hop 图扩展 |
| TaskMemBuffer | 当前任务步骤观察 | 单个任务 | 最近 K 条环形缓冲 |

Promptctx 再把这些来源映射到有预算的槽位。身份、约束、profile 不应和普通 episodic recall 在同一个 Top-K 竞争；任务步骤也不应在任务结束后污染长期记忆。

### 5.2 写入、召回和治理

AGI-saber 的写入链路大致是：

```text
用户消息/助手回复
  -> 规则或 LLM 抽取候选
  -> poison gate
  -> 分类（category/tags/slot_hint）
  -> embedding 或 TF 表示
  -> 去重/隐式合并
  -> 内存、PG、图层写入
```

召回按用途分流：

- profile 主要按类别枚举；
- recall 使用向量相似度和 TF 降级，并混合 importance；
- graph recall 在 seed 之外做有限邻居扩展；
- task memory 只拿最近任务观察。

合并阶段包含衰减、去重、冲突/替代和 TTL 淘汰。语雀文章特别强调“双门槛过期”：只有足够老且重要性足够低的记忆才淘汰，避免“老但重要”的事实被简单 TTL 删除。

### 5.3 设计意图

这里最值得借鉴的是“记忆不是一个表”：

- 数据结构服从使用模式，而不是统一塞进一个万能记录。
- 分类和来源在写入时保留，召回时才能做安全、相关性和预算过滤。
- 确定性的去重、衰减和淘汰尽量不依赖 LLM，降低延迟并保持可测试。
- LLM 负责抽取和长尾分类，但不直接成为记忆权限或删除事实的权威。

### 5.4 已发现的风险

当前 Go 代码中，`longterm.Consolidate` 的跨用户字段约束和 `GraphMemory` 的 UserID 传播仍需要加强；图扩展召回也不能只依赖相似度，必须再次检查 owner、quarantine、superseded、TTL 和敏感性。HTTP 层直接返回全量 LTM 或把过滤责任交给前端，是 ownership 反例。

### 5.5 VenAgent 取舍

- **Adopt**：记忆按生命周期和用途分层；来源、分类、TTL、冲突和审计成为领域事实。
- **Extend**：M05 通过强类型 provider 接入 ContextProjection，明确哪些内容进入 Prompt，哪些只保留在 memory service。
- **Compose**：用 VenAgent 的 owner、RunGrant、删除和 privacy 规则约束记忆召回；用 LangGraph checkpoint 保存图恢复现场而不是长期记忆。
- **Do-not-copy**：不复制 Neo4j schema、固定权重、具体阈值或“前端过滤全量记忆”的接口。

M05 Shape 需要提供的最小问题：候选如何归属 owner？来源和删除如何追踪？冲突是 supersede、quarantine 还是人工确认？每类记忆在预算竞争中是否可降级？

## 6. RAG：从文档摄入到有来源的回答

### 6.1 观察到的事实

语雀 RAG 文章给出的链路是：

```text
文档清洗 -> 标题感知/递归切分 -> Embedding
用户问题 -> Query 理解/改写 -> 多路检索 -> Rerank
         -> Prompt 组装 -> LLM 回答
```

设计偏好包括：

- Markdown 保留标题、列表、表格和完整代码块。
- 长 section 递归切分，使用小重叠避免断裂和重复。
- child chunk 用于精准召回，parent context 用于生成时恢复语义。
- Dense 擅长语义和同义表达，BM25 擅长 API 名、版本号、错误码和专有名词。
- 必要时叠加 Neo4j 图检索，使用 RRF 融合，再进行 rerank 和 small-to-big 回填。

本机 Go 代码的 `domain/rag` 和 `infrastructure/persistence/ragchunk` 进一步表明：PG 保存原文和 embedding，是可恢复的真相源；ES、Milvus 和 Neo4j 是增强索引或图层；依赖缺失时可降级为 semantic、keyword 或 unavailable。

### 6.2 设计意图

RAG 的重点不是“向量搜索”，而是减少三类错误：

- 资料不在模型参数中；
- 精确词和语义表达互相漏召回；
- 命中的小块缺乏生成所需的上下文和来源。

因此，摄入质量、召回覆盖率、排序质量、父子上下文、引用和删除一致性必须作为同一条链路验收。

### 6.3 代价与风险

- 三路系统带来索引一致性和运维复杂度。
- PG 删除成功而 ES/Milvus 删除失败时，可能留下孤儿索引；没有 outbox 或 reconciliation 就不能宣称彻底删除。
- 多 query 融合若以正文作为唯一聚合 key，重复正文可能被错误合并。
- PDF 外部命令、临时文件和图谱抽取需要独立的路径、大小、超时和沙箱边界。
- RAG evidence 与个人记忆具有不同 owner、TTL、来源和删除规则，不能共用一个“上下文池”。

### 6.4 VenAgent 取舍

- **Adopt**：父子块、混合检索、query rewrite、rerank、来源追踪和“真相源 + 增强索引”的分层问题意识。
- **Extend**：M08 以 `Evidence` 和引用为领域事实，按当前授权重新检索；将 RAG 作为内部服务和受控工具，而不是 Prompt 中的无来源文本。
- **Compose**：与 M04 owner、M06 工具授权、M07 图节点以及统一删除/恢复流程组合。
- **Do-not-copy**：不迁移 Milvus/ES/Neo4j 驱动、SQL 表、固定 RRF 权重或旧项目的删除顺序。

M08 Shape 需要明确：evidence-required 节点在检索失败时是否失败闭合？引用的来源版本如何冻结？删除后何时允许重新索引？

## 7. Tool、MCP、Skill 与 Sandbox

### 7.1 工具抽象

“Saber 工具调用全流程”把 Tool 解释为“名片 + 按钮”：

- Name、Description、Parameters 是给 LLM 看的名片；
- Execute 是系统本地的按钮，不能序列化给模型。

当前实现支持普通工具、带 context 的工具、结构化结果、retryable/code 错误和外部 MCP。工具注册表使用读写锁，调用方先拿 snapshot，再无锁遍历长任务，避免动态注册被 ReAct 阻塞。

### 7.2 工具路由与可靠性

AGI-saber 选择了自实现 JSON 风格，而不是完全依赖 provider 原生 function calling。它通过多层防线处理不稳定输出：Prompt 约束、代码块清洗、多个 schema 解析、白名单过滤、规则降级和 DAG 环检测。

这使模型协议更灵活，但也扩大了解析、兼容和错误处理面。MCP 还需要超时、状态码、重试、SSRF、owner、审批和审计边界，不能只把 endpoint 当作普通配置。

### 7.3 Sandbox

沙箱采用 Validator → Block/Warn → Executor → Audit：Docker、Local 和 Mock 是不同后端，命令长度、风险级别、资源限制、网络、文件系统和超时由策略控制。Local 只允许安全级别，Docker 提供隔离，Mock 用于测试和降级。

本机代码显示，MCP 全局注册、`context.Background()` 固定超时、本机执行参数复用错误、异步审计缺少完整身份等问题都不能直接迁移。

### 7.4 VenAgent 取舍

- **Adopt**：工具描述与执行实现分离；结构化错误；snapshot 减少长任务锁持有；sandbox 的校验、执行、审计分层。
- **Extend**：M06 使用 RunGrant、OperationGrant、ApprovalItem、credential broker 和幂等 operation identity；工具执行前再次授权。
- **Compose**：M07 只负责选择和编排，M06 持有工具、审批、沙箱和副作用事实；ContextProjection 只投影能力，不授予权限。
- **Do-not-copy**：不允许用户输入直接注册全局 MCP endpoint，不把 JSON Prompt 解析结果视为授权，不复制旧版命令执行和路径配置。

M06 Shape 需要明确：哪些工具必须审批？取消发生在执行前、执行中和结果未知时分别如何处理？副作用未知时如何对账而不是盲目重试？

## 8. 子 Agent、文档库与长任务

### 8.1 观察到的事实

AGI-saber 将 research、writer、review、doc 等子 Agent 组织成注册表和固定任务链。报告类任务可以按 `research → writer → review → doc` 顺序执行，文档 Agent 负责本地文档写入并触发 RAG 同步。

长任务通过 TaskGraph、TaskState、快照、SSE 事件和取消机制对外呈现进度。图节点持有短观察和稳定引用，最终由 Generator 合成答案。

### 8.2 设计意图

子 Agent 的价值不是“再启动几个模型”，而是把不同职责、输出契约和失败边界隔离开：

- research 产出事实和来源；
- writer 产出草稿；
- review 发现缺口；
- doc 负责持久化和索引副作用。

这种分工与 Replanner 结合后，可以让任务先完成必要调查，再根据观察补充步骤。

### 8.3 VenAgent 取舍

- **Adopt**：显式子 Agent 输入/输出契约、任务级进度和文档产物引用。
- **Extend**：M07 通过 LangGraph 子图或受控 subgraph 管理恢复，M08 只接收明确的文档/evidence 端口。
- **Compose**：将最终回答、文档 artifact、evidence 和 AgentRun 分开建模；前端显示关联状态而不是把所有中间文本伪装成正式消息。
- **Do-not-copy**：不把硬编码子 Agent 名称、共享全局 Agent 或本地文件写入当作 VenAgent 通用能力。

## 9. 平台、降级与观测

### 9.1 观察到的事实

AGI-saber 在启动时分别连接 PostgreSQL、Milvus、Elasticsearch、Kafka、Neo4j 和 sandbox，并允许部分依赖缺失后以降级模式运行。配置按 Server、LLM、Storage、RAG、Memory、Harness、Sandbox、Security、Graph、Auth、Observability 等分组，使用严格 YAML 字段解析和环境展开。

代码中还有并行 bootstrap、统一 `/api/status`、结构化日志、pprof 保护、Compose healthcheck 和优雅关闭等工程化尝试。

### 9.2 必须保留的反例

- `/readyz` 恒返回 200，不能作为真实依赖 readiness 证明。
- InfraStatus 是启动快照，不会自动反映后续故障。
- Kafka 写失败只记录日志，没有 outbox、持久重试或对账。
- PostgreSQL DDL 逐条执行且错误可能只告警，存在半升级风险。
- Compose 中存在开发凭据和外网暴露设置，不能当生产模板。
- 当前项目没有完整的平台级备份/灾备流程；任务快照不等于数据库恢复方案。

### 9.3 VenAgent 取舍

- **Adopt**：能力分组配置、严格字段校验、结构化日志、启动报告、显式降级状态和平台适配器隔离。
- **Extend**：M09 只在真实吞吐/多 worker 证据出现后增加调度和 operator 能力；M04--M08 必须各自负责安全、失败和可观测性。
- **Compose**：将 LangSmith trace、LangGraph checkpoint、AgentRun 状态、M06 审计和平台指标分开观察，并用稳定 ID 关联。
- **Do-not-copy**：不把“依赖可选”理解为“依赖失败也返回成功”，不把任务快照称作灾备，不提前创建 queue/scheduler。

## 10. 对 VenAgent 的总体决策

| 决策 | 内容 |
|---|---|
| Adopt | 复杂度路由、职责分层、Context 槽位、记忆生命周期、混合 RAG、工具描述/执行分离、sandbox 分层、可验证降级 |
| Extend | 用 owner、RunGrant、OperationGrant、Evidence、AgentRun、LangGraph checkpoint 和 ContextProjection 重建旧思想 |
| Compose | M04 的所有权 + M05/M08 的事实来源 + M06 的执行授权 + M07 的图编排 + M09 的平台证据 |
| Do-not-copy | 全局 Agent、隐式 Prompt、关键词作为授权、旧 TaskState、私有 checkpoint 表、未审批命令、前端过滤全量数据、无对账删除 |
| Build only when needed | 新调度器、分布式队列、operator surface、复杂图数据库能力和平台灾备系统 |

VenAgent 当前规格已经明确：

- `ConversationMessage`、`AgentRun`、LangGraph State、ContextProjection 和 M06 工具事实互不替代；
- `thread_id=run_id` 只是 adapter 映射，不是业务身份；
- Prompt 只做本次调用的投影，不授予权限，也不承担恢复、审计和取消；
- 未实现的 M05/M06/M08 能力使用 absent/unavailable 表达，不创建空 provider；
- 每个模块通过自己的 provider/consumer port 进入后续 Shape。

因此，AGI-saber 最适合成为问题清单和风险样本，而不是 VenAgent 的目录模板。

## 11. 后续各模块 Shape 的问题清单

### M04 ownership-lifecycle

- 文档、记忆、RAG evidence、工具和 artifact 的 owner 事实分别在哪里？
- 删除、撤销、run 取消、approval 关闭和索引清理的顺序是什么？
- readiness、降级和无权状态如何对用户可见？

### M05 memory-system

- 哪些消息有资格抽取长期记忆？如何做 poison、来源和敏感信息过滤？
- recall、profile、task memory 如何竞争预算？
- conflict、quarantine、superseded、TTL 和删除如何审计？

### M06 tool-execution

- 工具 registry、MCP endpoint、Skill、credential 和 sandbox 的 owner 与生命周期是什么？
- approval 是批量还是逐项？interrupt 恢复重跑时如何保持幂等？
- 未知工具结果、取消竞态、SSRF、路径和命令边界如何 fail closed？

### M07 agent-orchestration

- Planner、Replanner、Executor、Generator 和子 Agent 的输入输出契约是什么？
- State 只保存哪些恢复所需引用？哪些事实必须回查 M04/M05/M06/M08？
- 并行、竞速、重试、动态节点和 contract mismatch 如何验证？

### M08 rag

- 文档版本、chunk、index、evidence 和 citation 如何归属和删除？
- 召回失败、rerank 不可用、无结果和 evidence-required 节点分别如何处理？
- PG 真相源与增强索引如何通过 reconciliation 证明一致？

### M09 platform-governance

- 哪些依赖缺失可降级，哪些必须阻止 readiness？
- 事件、日志、checkpoint、审计和业务状态的保留策略是什么？
- 何时才有真实证据支持 queue、scheduler、worker 或 operator surface？

## 12. 来源与 provenance

### 语雀设计材料

- [架构总览](https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/ywv5hhdu3tnzimhc)：总体能力、路由优先级、三层记忆、混合 RAG、sandbox 和可选基础设施。
- [从 Static DAG 到 Plan-and-ReAct](https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/ltm0t3337f5k0glu)：Replanner、动态节点、状态机和增量计划。
- [记忆系统详细介绍](https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/qwsuulxsongrhiak)：五种记忆形态、写入/召回/合并、SlotFilter 和预算。
- [RAG](https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/gbkmp56a6ki3z383)：清洗、切片、混合检索、RRF、rerank 和评测入口。
- [Saber 工具调用全流程](https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/pwceramosngpwuww)：Tool、registry、路由、Planner、TaskGraph、竞速和 RAG-as-Tool。

语雀访问时间：2026-08-04。语雀内容是设计说明和研究输入，不是 VenAgent 的行为契约。

### 本机 AGI-saber 静态证据

- 本机路径：`D:\VSCProject\AGI-saber`。
- 当前 Go 工作副本：`fead7687a82965b3c0106728089ccde0cc0eb3e8`。
- 重点路径：`internal/application/chat`、`internal/domain/memory`、`internal/domain/rag`、`internal/domain/promptctx`、`internal/domain/tool`、`internal/domain/sandbox`、`internal/infrastructure`、`docs/architecture/ARCHITECTURE_MAP.md`。
- VenAgent 既有 ADR 记录的冻结 Python 参考提交：`2b995cdd8b2fb413bfb34c41456ec0bda92e6c2a`。该提交只作为静态行为线索，不进入 VenAgent 运行或同步路径。

### VenAgent 约束

- `docs/comet/specs/refactor-roadmap/spec.md`
- `docs/comet/specs/agent-runtime/spec.md`
- `AGENTS.md`

这些文件优先决定 VenAgent 的身份、State、ContextProjection、模块所有权、验证和不建设边界。

## 13. 明确非目标

- 不把 AGI-saber 的 Go/Python 代码、表结构、驱动、Compose 或默认凭据迁移到 VenAgent。
- 不把语雀文章中未被代码证实的目标状态写成已实现事实。
- 不在 M04--M09 Shape 之前创建 memory、tool、sandbox、task、subagent、document、vector 或 queue 的未来空目录。
- 不建立通用 `AgentRunEvent`、第二套 State、事件溯源或 LangGraph 私有表依赖。
- 不把这份文章视为最终架构决策；任何改变 VenAgent 用户可见行为的结论，仍需进入对应 Native change 的 Shape、批准、Build 和 Verify。
