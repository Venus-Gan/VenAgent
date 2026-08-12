# VenAgent 核心重构路线完整目标规格

## 1. 目标

VenAgent SHALL 以可用户验收的纵切推进核心重构。LangGraph 管理单个 AgentRun 的图执行与 checkpoint；VenAgent 领域模型管理 conversation、消息、运行、权限、记忆、工具、RAG 和用户体验。每个后续 change 都经过独立 intake、Shape、批准、Build、Verify 与 Archive，路线顺序不自动授权实现。

## 2. 已有基础与统一不变量

- `frontend-foundation` 与 M04 ownership 的技术/安全基线已经存在；`agent-runtime-foundation` 负责把旧 M01--M03 的 thread/turn/连接内执行契约替换为新运行基础。
- 正式业务事实使用 `ConversationMessage`、`AgentRun`、RunGrant及各模块领域模型；LangGraph checkpoint只保存恢复当前 run图所需的 State。
- `conversation_id`、`message_id`、`run_id`、`owner_id`、工具调用 ID、evidence/artifact ID含义分离；adapter内 `thread_id=run_id` 不成为业务 ID。
- ContextProjection是按调用生成的纯派生值；Prompt、State、长期记忆、工具事实与 RAG evidence互不替代。
- 业务用例不依赖具体 adapter，infra不承载 use case，HTTP不承载业务事实；不为未来能力预建目录、共享层或事件系统。
- AGI-saber只作为行为、接口、依赖、测试与风险事实来源，不迁移其 Go实现、表结构、运行期 DDL或内部架构。

## 3. Change 顺序

### 3.1 `agent-runtime-foundation`

端到端替换旧运行基础：ConversationMessage、持久 AgentRun、单活跃、claim/lease/fencing、per-run LangGraph checkpoint、RunGrant、新 API/SSE、前端 message/run/partial投影，以及最小 ContextProjection起点。

归档门槛是实际完成发送、后台运行、断线重连、刷新恢复、最终回答、取消和失败重试；不实现长期记忆、工具、审批或 RAG。

### 3.2 `memory-context`（M05）

在已稳定的消息/run/ProjectionInputCollector边界上实现长期记忆事实、来源、提取资格、去重、召回、TTL/importance、冲突/quarantine/superseded、审计与删除，并交付对话 recall 的用户体验。

- M05首先拥有 memory候选、过滤器与 memory section策略；它不得接管 AgentRun State或工具权威事实。
- ContextProjection 的 section/filter/mode/槽位编排表在 M05 Shape中按实际 memory/RAG/tool扩展需求复核。foundation中的表只是可修订起点，不得因“记忆最先做”而把未来工具/RAG字段伪造成已实现。
- 尚未存在的 tool、planner、RAG provider用显式 unavailable/absent capability表达，不创建空实现。M06--M08到来时通过类型明确的 provider扩展同一投影边界。

### 3.3 `tool-aware-agent-graph`（M06 + M07）

作为同一用户可验收纵切交付受控工具和真实模型→工具→模型图，但保持模块所有权分离：

- M06拥有工具注册、策略、sandbox、OperationGrant、幂等执行、审计、approval batch/item及外部事实对账。
- M07拥有 Planner、Tool Selector、Observation、Replanner、Generator、LangGraph State、interrupt/resume、任务计划、节点重试/并行和子 Agent边界。
- State只保存继续图所需的调用引用与摘要；M06仍是工具/审批/安全事实权威。Prompt通过 ContextProjection得到当前能力和脱敏摘要。
- 真实前端必须完成工具选择、授权、逐项审批、执行、重规划、断线恢复、取消和副作用幂等验收。

### 3.4 `rag-evidence`（M08）

实现文档上传/解析/版本/删除、检索、evidence引用与评测，并按证据决定基础向量、混合、改写、重排或图检索。RAG evidence与个人记忆是不同领域，归属、TTL、权限和删除不能共用。

RAG作为内部领域服务与原生受控工具供 Agent图调用；未来 MCP facade不得替代内部授权/检索接口。重试默认按当前权限和索引重新检索，旧 evidence只在来源仍有效且明确采用时复用。

### 3.5 `scheduler-scale`（M09，可选且最后）

只有真实吞吐、部署或运维证据证明 PostgreSQL queued-run轮询、FIFO、公平性、worker并发或当前观测不足时才创建。它 MAY 引入外部队列、优先级、分布式 worker治理、备份恢复或 operator surface，但不得替代前序模块自身的安全、测试和可观测性。

没有真实需求时 M09不创建、不作为项目完成的形式门槛；若创建，必须是路线最后的规模化/收尾 change。

## 4. ContextProjection 演进规则

- foundation建立 `ProjectionInputCollector -> ContextProjectionService -> ContextProjection` 单向管线和统一 ContextBlock/BudgetReport。
- 每个业务模块只实现类型明确的 provider/consumer port并返回自身权威事实或候选；不得直接拼完整 system prompt，也不得把新字段塞入 State充当模块数据库。
- section至少允许 system policy、identity/capability、current task、conversation、memory、plan/progress、tool/approval、evidence/artifact与output contract等类别；未实现 section明确 absent而非伪造内容。
- filter至少覆盖 owner/tenant/authorization、生命周期/TTL、来源可信度、任务相关性、role可见性、敏感信息、去重/冲突和预算；具体顺序、阈值、mode和槽位预算在拥有模块 Shape中可修改。
- 每次修改都必须记录：权威来源、进入 Prompt还是 State、失败/降级行为、预算竞争、来源引用、安全过滤和前端可见性。不得形成第二套状态系统或通用规则引擎。

## 5. 模块 intake 与目录决策

- 每个路线模块按项目规则执行 fixed intake、`venagent-module-router`专项路由、AGI-saber最小必要对照和前端检查点，记录渠道可用性与 Adopt/Extend/Compose/Build结论。
- 若 Shape涉及新增/合并 package、Vue module、共享表面、路由或跨模块所有权，使用 `product-capability`记录最小目录增量与明确不创建项。
- 优先读取路由矩阵指定旧项目路径；只有调用链、共享模型、配置或测试证据不足时扩大最小审计范围并记录原因。
- module intake是 Shape输入，不建立独立 phase、approval或并行生命周期。

## 6. 发布与验证

- 每个 change同时负责其最小后端、API、前端、安全、降级、可观测性和真实浏览器体验；不把 UI或运维补债推到 M09。
- 前后端协议、schema和 runtime contract作为协调发布面；不兼容变更必须在同一 change完成，不允许可用状态下混跑半套旧协议。
- 运行时 change按领域单元、PostgreSQL并发/恢复、LangGraph公开契约、HTTP/SSE、owner隔离、Vue E2E与真实浏览器分层验证。
- 高风险工具、文件、命令、凭据和外部网络只有 M06 Shape批准后才能进入 Build，并执行最小权限与故障预案。

## 7. 明确不建设

- 不建设通用 AgentRunEvent、event sourcing、第二套 State、分布式事务、回答分支或旧版本兼容层。
- 不提前创建 M05 memory、M06 tool/sandbox、M07 task/subagent、M08 documents/vector或M09 queue/operator目录。
- 不把 LangSmith trace当业务数据库；LangSmith用于追踪与评测，LangGraph用于运行图，Comet Native用于项目开发生命周期。
