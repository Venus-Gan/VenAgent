# Agent 运行时上下文重构讨论记录

> 状态：讨论中（Pre-Comet）  
> 建立日期：2026-07-31  
> 用途：保存本轮关于 System Prompt、LangGraph State、checkpoint、AgentRun 和对话事实的已确认决定，防止后续讨论丢失上下文。  
> 约束：本文不是 Comet spec、不是 active change，也不授权实现。所有问题确认完成后，才以本文为研究输入进入 Comet Native 流程。

## 1. 讨论目标

本轮讨论不局限于记忆系统，而是面向 VenAgent 最终重构目标，厘清以下相互关联的边界：

- System Prompt 中的动态上下文如何产生；
- LangGraph State 与 checkpoint 承担什么职责；
- 对话事实、执行生命周期、工具事实分别由谁持有；
- 长任务的暂停、恢复、取消、重试、并行和版本失效如何表达；
- 现有 `ConversationRun`、`ActiveRun`、`TurnRecord` 后续如何替换。

AGI-saber 只作为行为事实参考，不作为 Go 架构或存储模型的迁移模板。最终设计应充分利用 LangGraph 的公开 State/checkpointer 契约，同时保持 VenAgent 自有业务模型不依赖 LangGraph 私有表结构。

## 2. 总体模型（已确认）

最终采用四层模型：

| 层 | 权威职责 | 明确不承担 |
|---|---|---|
| `ConversationMessage` | 对话中真实发生的不可变消息 | 执行状态、计划、工具原始结果 |
| `AgentRun` | 一次执行的业务生命周期与外部控制面 | 图内阶段、节点现场、完整上下文 |
| LangGraph State/checkpoint | 单次 run 的可恢复执行现场与 super-step 历史 | 业务查询索引、跨 run 控制、工具审计事实 |
| `ContextProjection` | 每次模型调用实际看到的动态上下文 | 任何权威事实的永久存储 |

另保留一个仅存在于当前进程的 `ActiveRunContext`，容纳 cancel token、claim/lease、初始请求 Actor/session 归因、当前 `ExecutionAuthorization` 和流式请求临时信息。它不持久化，也不是恢复依据。

### 2.1 身份命名（已确认）

目标架构统一使用：

```text
conversation_id        业务对话身份
run_id                 一次 AgentRun 身份
LangGraph thread_id    仅存在于 adapter/config，值恒等于 run_id
```

- 业务模型、数据库、API、前端和业务日志不再使用 `thread_id` 表达 conversation。
- 只有 LangGraph adapter 层使用框架要求的 `configurable.thread_id`，并通过单一 helper 从 `run_id` 构造 config。
- `AgentRun` 不保存可推导的 `checkpoint_thread_id`；checkpoint chain identity 由 `run_id` 唯一确定。
- 目标 API 使用 `/api/conversations` 与 `{conversation_id}`；当前 `/api/threads`、`ThreadRecord`、`ThreadStore` 和前端 `threadId` 在基础契约替换时统一重命名，不保留旧 API/数据兼容层。

## 3. System Prompt 与 State（已确认）

### 3.1 基本边界

System Prompt 和 LangGraph State 不互相替代：

- State 是机器可读、可 checkpoint、供节点和路由使用的运行事实。
- System Prompt 是在模型调用前由 `ContextProjection` 生成的文本/消息投影。
- 同一事实只能有一个权威来源；进入 Prompt 的内容只是投影，不成为第二份状态。
- Prompt 不承担恢复、并发合并、取消或审计职责。

### 3.2 State 保存的内容

State 保存任务继续运行所必需的图内数据，包括：

- 当前 `phase`；
- 任务计划、步骤与节点进度；
- 当前 run 的 working messages 或等价执行消息；
- 并行分支返回的 observations；
- artifact references；
- `tool_call_id`、幂等键及工具结果摘要/引用；
- 结构化失败摘要、可重试性和技术重试次数；
- `pending_approval_id` 等图内等待引用；
- 最终回答或最终结果；
- ContextProjection 所需但无法从权威模块即时重建的任务现场。

State 不保存：

- `AgentRun.status` 的副本；
- cancel 请求的权威状态；
- 权限、工具可用性、沙箱策略或审批有效性的权威副本；
- 异常对象、完整 traceback、大段工具原始响应；
- M06 已负责保存的工具执行与安全审计事实。

### 3.3 System Prompt 动态投影的来源

每次模型调用前，`ContextProjection` 从对应权威来源组装：

| Prompt 内容 | 来源 | 恢复后策略 |
|---|---|---|
| 稳定系统规则、角色和输出约束 | 运行时配置/Prompt 资产 | 读取当前有效版本 |
| 当前任务计划、阶段和进度摘要 | LangGraph State（M07） | 沿用 checkpoint |
| 当前用户请求与相关对话 | `ConversationMessage` + 当前 State | 重新投影 |
| 可访问长期记忆 | M05 | 重新检索与鉴权 |
| 工具目录、可用性与执行约束 | M06 及相关能力注册表 | 重新查询 |
| 权限、身份和安全决策 | M04/M06 的权威接口 | 重新查询 |
| 沙箱状态与策略 | M06/沙箱权威组件 | 重新查询 |
| 审批状态 | M06 审批事实 | 重新查询有效性 |
| 工具调用与观察摘要 | State 中的引用与摘要，原始事实在 M06 | 用稳定 ID 对账 |

恢复 run 时，任务计划、节点进度和观察摘要沿用 checkpoint；权限、工具可用性、沙箱策略、审批有效性以及可访问记忆必须重新查询，不能信任暂停前的快照。

### 3.4 ContextProjection 确定性契约

VenAgent 不构建一份贯穿整个 run 的大 System Prompt。Planner、Tool Selector、Replanner、Generator 等每个模型节点在调用前，分别生成一次角色专用的 `ModelCallContext`。

模型节点先从各权威模块读取一次当前视图，再调用纯投影服务：

```text
ProjectionInput
  = ModelRole
  + RunStateView
  + ConversationContext
  + IdentityView
  + MemoryContext
  + ToolCapabilityView
  + SandboxView
  + ApprovalView
  + EvidenceContext
  + ModelLimits
  + projection_policy_version
```

- `ContextProjection` 本身不查询数据库、不访问外部服务、不修改 State。
- 相同 `ProjectionInput` 和相同策略版本必须产生相同的 `ModelCallContext`。
- 恢复后重新读取 M04/M05/M06/M08，允许外部权威视图发生变化；确定性只约束已经取得输入后的投影过程。
- 单次投影使用同一次采集得到的读取集合，避免构建过程中反复读取互相不一致的权限、工具或记忆状态。

### 3.4.1 ProjectionInputCollector（已确认）

agent runtime/M07 拥有一个无状态的小型应用编排组件 `ProjectionInputCollector`。各权威模块只实现类型明确的 consumer port，Collector 负责调用顺序、超时、降级和来源版本封装：

```text
LangGraph 模型节点
  -> ProjectionInputCollector
     -> IdentityContextProvider
     -> ConversationContextProvider
     -> MemoryContextProvider
     -> ToolContextProvider
     -> EvidenceContextProvider（M08 存在时才注册）
  -> ProjectionInput
  -> 纯 ContextProjectionService
  -> ModelCallContext
```

- M07/agent runtime 定义消费方 port；M04/M05/M06/M08 分别实现，不让某个业务模块成为全部上下文的总管。
- Collector 属于 application orchestration，不放入 `infra/`，不建设通用 event bus、规则引擎或第二套状态系统。
- Collector 不写 State、不调用 LLM、不修改权威模块，也不建立跨 M04/M05/M06/M08 的分布式事务。
- Collector 没有数据库表、历史、持久缓存、checkpoint、rollback 或恢复职责；LangGraph checkpointer 是唯一的持久化任务快照与恢复机制。
- `ContextProjectionService` 继续保持纯函数，只接收已经采集、鉴权和脱敏的 `ProjectionInput`。

每次模型调用使用固定顺序：

1. 校验 RunGrant，并派生/复核当前 `ExecutionAuthorization`。
2. 读取当前 conversation snapshot 与调用节点已有的 State/checkpoint snapshot。
3. 在授权通过后并行读取 M05 memory、M06 tool/sandbox/approval，以及当前已存在的可选 M08 evidence provider。
4. 封装本次调用的 `ProjectionInput`。
5. 调用纯 `ContextProjectionService` 生成角色专用 `ModelCallContext`。

身份/RunGrant 校验失败时不得继续读取 owner memory、工具或 evidence。`ProjectionInput` 的采集元数据至少表达：

```text
ProjectionInput.metadata
  projection_request_id
  run_id
  checkpoint_id
  model_role
  runtime_contract_version
  captured_at
  source_statuses
  source_versions
```

每个来源状态使用 `ok | degraded | unavailable | stale`。来源版本只证明本次调用采用了哪一版外部事实，不表示跨模块事务一致性，也不形成可回滚快照。

默认超时与失败策略为：

| 来源 | 默认超时 | 策略 |
|---|---:|---|
| M04 RunGrant/Identity | 2 秒 | fail closed |
| Conversation | 2 秒 | fail closed |
| M06 tools/sandbox/approval | 3 秒 | fail closed |
| M05 memory | 2 秒 | degraded 并省略 |
| M08 evidence | 5 秒 | evidence-required 节点失败；其他节点 degraded |

- 超时值通过配置调整，不写死在领域逻辑中。
- 超时只终止当前投影请求，不改变来源权威状态。
- M08 尚未实现时不注册 Evidence provider，也不创建无行为的空 adapter 或硬依赖。

### 3.5 ContextBlock 与投影输出

各模块提供的候选上下文先转换为统一的原子 `ContextBlock`，至少表达：

```text
block_id
category
source
content
priority
mandatory
token_count
source_ref
sensitivity
captured_at
```

- 裁剪以完整 block、完整消息、完整观察或完整证据为单位。
- 不从中间截断 JSON、工具参数 schema、消息或引用。
- `source_ref` 指向 M01/M05/M06/M07/M08 的权威事实；Prompt 内容本身不成为新的权威副本。
- 敏感信息必须在进入 block 前由来源模块脱敏；ContextProjection 不接收凭据、秘密环境变量或可执行权限清单。

投影结果为结构化模型调用上下文，而不是单个字符串：

```text
ModelCallContext
  system_messages
  messages
  tools
  manifest
  budget_report
```

- System messages 保存稳定行为规则、安全原则、当前节点职责和输出契约。
- Human/AI messages 保存被选中的线性对话历史与当前请求。
- Tool messages 保存经过清洗的工具观察或稳定引用。
- Tools 只包含本次调用真正允许模型选择的工具 schema。
- RAG evidence 作为有来源的证据块进入上下文，不能伪装成系统指令。

### 3.6 角色专用投影策略

不同模型节点不共享一份 `memPrefix`，而使用各自的选择策略：

| 模型角色 | 主要上下文 | 默认排除 |
|---|---|---|
| Planner | 当前请求、任务约束、相关历史、相关记忆、可用能力摘要 | 所有工具完整 schema、大量旧观察 |
| Tool Selector | 当前节点、当前允许工具完整 schema、参数契约、最新必要观察 | 大量对话历史、无关记忆与工具 |
| Replanner | 原计划、完成/失败节点摘要、剩余目标、当前可用能力 | 全部工具原始输出、无关历史 |
| Generator | 当前请求、结果摘要、引用、产物、相关历史、输出契约 | 工具目录、审批内部细节、Planner 内部指令 |

- Planner 只接收能力摘要；选定候选工具后，Tool Selector 才接收相应完整 schema。
- 工具很多时先由能力/路由层过滤候选集合，不能通过截断完整 schema 来节省 token。
- 后续新增模型角色时必须显式定义自己的 ProjectionPolicy，不能默认继承一份全局 Prompt。

### 3.7 完整模型调用预算

Token 预算覆盖完整模型输入，而不只计算动态 slot：

```text
input_budget
  = model_context_limit
  - reserved_output_tokens
  - provider_overhead
  - safety_margin
```

预算范围包括 System messages、对话消息、当前请求、工具 schemas、State 摘要、记忆、RAG 证据和 Tool messages。

- 优先使用模型对应的 tokenizer；无法获得时使用保守估算器，并在 `BudgetReport` 标记为 estimated。
- 所有角色均不可裁剪安全/权限约束、当前请求、当前节点输出契约、执行节点必需 State，以及被调用工具的完整参数契约。
- 可选内容按角色策略稳定排序后逐 block 裁剪。排序至少使用 mandatory、priority、relevance、captured_at 和 block_id；`block_id` 负责稳定打破平局。
- ContextProjection 不临时调用 LLM 做摘要。需要摘要时，由显式 LangGraph 节点或 M05/M08 预先生成并写入其权威位置。

### 3.8 上下文超限与降级

- 可选内容超限时，删除最低优先级完整 block，并在 manifest 记录原因。
- 单个大型工具/RAG 结果超限时，使用 M06/M08 或 State 已存在的摘要和 artifact reference。
- 如果必需内容本身超过输入预算，ContextProjection 返回结构化 `context_overflow`，不得强行调用模型。
- `context_overflow` 至少表达模型角色、必需 token、可用 token、超大 block 和建议动作。
- LangGraph 根据结果显式进入 compact state、reduce tools、split task 或 fail 路径；压缩必须成为可 checkpoint、可观察的图节点，不能隐藏在投影器内部。

M04 权限或 M06 强制安全快照不可用时应 fail closed。M05 记忆等非强制来源不可用时可以省略并标记 degraded；M08 是否可降级由当前节点是否要求证据决定。

### 3.9 安全复核与可观测性

Prompt 中的工具限制只是模型引导，不是执行授权。M06 在工具真正执行前仍须重新校验当前 Actor、权限、参数、审批和 sandbox 策略。

`ProjectionManifest`/`BudgetReport` 至少可记录：

```text
projection_policy_version
model_role
selected_block_ids
omitted_block_ids_and_reasons
source_versions
input_token_count
reserved_output_tokens
token_count_method
context_digest
```

- manifest 进入 LangSmith trace 或结构化日志，不写入 LangGraph State，也不为此新增事件表。
- 默认不永久保存完整 Prompt；诊断信息优先保存 block 引用、版本、摘要和 digest。
- Prompt 文案或 ProjectionPolicy 可单独版本化；只有改变 Graph/State/节点结构化契约时才递增 `runtime_contract_version`。

### 3.10 最小实现边界

当前决定只要求最小的 `ContextProjectionService`、统一 `ContextBlock`、角色级 `ProjectionPolicy`、`TokenCounter` 和 `BudgetReport`。不创建通用 Context event bus、通用规则引擎或第二套状态系统。

### 3.11 ProjectionPolicy、过滤器与区段编排（暂定，模块 Shape 可修订）

本节补足 AGI-saber `promptctx` 的“Mode -- Slot schema -- SlotFilter”思想在 VenAgent 中的等价设计，但不把其六种槽位、四个 Mode 或任一阈值照搬为不可变规格。

以下边界在后续模块中保持不变：

- LangGraph 当前模型节点决定 `ModelRole`；调用方不得传入任意 Mode。未知角色、缺失策略或必需区段缺失均返回结构化配置错误，不能 fallback 到普通 chat。
- `ProjectionPolicy` 只决定“本次模型调用需要什么、放到哪里、优先级如何”；权威模块仍决定“能读到什么”。Prompt 投影不能授予数据或工具权限。
- 每个区段使用来源类型明确的 selector。M05、M06、M08 等模块负责执行各自的查询、鉴权、排序、去重与来源级过滤；`ContextProjection` 只对已返回的完整 `ContextBlock` 做区段预算和全局预算选择。
- 不创建无行为的 memory/tool/evidence provider 或占位区段。一个区段仅在对应能力已经存在且有实际消费者时注册。

暂定的策略形状如下，字段名称和数据结构在具体 Shape 中可调整：

```text
ProjectionPolicy
  model_role
  section_specs[]
    section_kind
    placement                 # system_messages | messages | tools
    required
    priority
    token_budget
    failure_policy
    source_specific_selection # 由对应模块定义的强类型选择条件
```

`source_specific_selection` 不采用跨来源的万能 `SlotFilter`。例如 M05 可定义 `MemorySelection`（类别、标签、相关度、数量、时效、访问范围与去重）；M06 可定义 `ToolSelection`（能力、风险、允许动作、候选工具和观察范围）；M08 可定义 `EvidenceSelection`（来源、相关度、新鲜度、数量与引用要求）。具体字段、默认值和评分语义都必须在各自模块 Shape 中依据真实 repository、provider 和验证结果决定。

foundation 的预期起点仅编排当时真实存在的基础区段：稳定系统规则、当前有效安全约束、线性 conversation、`task_input`、已有执行摘要和输出契约。`execution_summary` 仅在对应 State 已经具有安全摘要时出现。M05 实现后可为实际消费记忆的角色追加 `profile_memory` 与 `recalled_memory`；M06/M07 实现后追加 planner state、节点观察、工具能力、工具观察和审批约束；M08 实现后才追加独立的 `evidence` 区段，不能把可引用证据混入普通 recalled memory。

上述起点、区段名称、每个角色的完整编排表、每段 token budget、记忆分类和过滤阈值均为可修订的设计输入，不是跨模块永久契约。每个模块进入 Comet Shape 时必须：审计已存在 `ModelRole`、provider、数据分类与调用图；更新受影响 `ProjectionPolicy` 表和 `projection_policy_version`；补充 selector、预算、失败/降级和安全测试；以真实交互验收和观测结果校准策略。只有“权威来源不迁移到 Prompt、未知角色不静默降级、来源过滤与投影预算分层、未实现能力不占位”保持为硬边界。

## 4. 工具状态与 M06/M07 边界（已确认）

- M06 持有工具执行的权威事实、安全决策、审批事实和审计信息。
- M07 State 只持有继续执行需要的调用引用与结果摘要。
- 两者通过稳定的 `tool_call_id` 和幂等键关联。
- 工具参数错误、权限拒绝、工具不可用或任务层失败返回图，由 replanner 决定换工具、改计划或终止。
- 工具执行重试必须复用原 `tool_call_id` 和幂等键，避免重复外部副作用。
- 重新规划产生的新执行拥有新的节点执行身份；它不等同于同一次执行的技术重试。

## 5. LangGraph checkpoint（已确认）

### 5.1 承担的职责

LangGraph checkpoint/history 作为图内执行现场和任务快照机制，承担：

- 每个 super-step 后的 State 快照；
- 暂停、恢复和 interrupt 现场；
- 并行分支在图内的执行历史；
- 内部诊断、必要时的历史查看；
- 基础设施故障后继续同一个 run。

checkpoint 不替代 `AgentRun` 的业务查询和控制记录，也不替代 M06 的工具/审批/安全事实。VenAgent 不直接查询、扩展或绑定 LangGraph checkpointer 的私有物理表。

### 5.2 checkpoint 身份

- 执行 checkpoint 以 `run_id` 隔离，不直接以业务 `conversation_id` 作为执行现场身份。
- LangGraph adapter 使用 `configurable.thread_id=run_id`，`AgentRun` 不持久化可推导的 `checkpoint_thread_id`。
- `conversation_id` 只表达业务关联。
- 用户重试使用新的 `AgentRun` 和新的 checkpoint 链；当前不支持重新生成或分叉。
- worker 崩溃接管继续原 `AgentRun` 和原 checkpoint 链，不创建新 run。

### 5.3 版本兼容策略

不兼容旧 checkpoint，不编写 checkpoint migration，也不保留旧 Graph。

- 使用一个 `runtime_contract_version`。
- Graph 拓扑、State schema 或节点输入输出契约发生破坏性变化时递增。
- 恢复时要求 checkpoint 版本与当前版本完全一致。
- 不一致则把 run 标记为 `incompatible`，禁止继续执行；用户可基于原消息新建 run。
- 普通重启、前端/文档修改和不改变结构化契约的 Prompt 文案修改不递增版本。
- checkpoint 失效不删除对话消息、长期记忆、M06 工具/审批/审计事实和 `AgentRun` 终态。

## 6. State 更新、并行与失败（已确认）

### 6.1 并行更新

- 节点只返回自己的增量结果，不原地修改传入 State。
- 并行节点不共同覆盖整个 `node_states` 字典。
- observations、artifact references、工具调用引用统一包含在 `node_outcomes` 中，通过 reducer 合并，避免多个平行列表失去关联。
- 每个并行结果携带稳定 `node_id`。
- `plan`、`phase`、`final_answer` 只由对应协调节点更新。
- 汇总节点生成最新任务视图并决定下一步。

### 6.2 失败与重试

- 网络超时、模型限流等瞬时故障由当前节点进行有上限的技术重试。
- 超过上限后回到图中形成 checkpoint，不允许节点内部无限重试。
- 任务或策略层失败交给 replanner 或终止路径处理。
- State 只保存结构化失败摘要、可重试性、次数和权威记录引用。
- M06 保存完整工具失败事实与审计信息。

### 6.3 最终 State 顶层 schema

采用显式、带类型的顶层 channel，不使用 `dict[str, Any]` 或通用 `metadata` 容器：

```text
RunState
  task_input
  phase
  plan
  node_outcomes
  approval_wait
  final_answer
  failure
```

- 顶层优先使用 `TypedDict`；节点只返回局部更新。
- Graph 可分别定义公开 input schema、内部 State schema 和 output schema，避免把全部内部现场暴露给调用方。
- 不保留通用 `working_messages`。M01 保存正式对话消息，`ContextProjection` 按模型角色构建调用消息；特定子图如确实需要消息循环，应使用自己的私有 State。

### 6.4 task_input、phase 与 plan

`task_input` 是本次 run 的不可变执行快照，至少包含 `input_message_id`、消息内容和 attachment references。原始消息的业务权威仍在 M01；State 快照保证恢复后继续使用同一任务输入。

`phase` 只表示图内路由位置，可包含 planning、selecting_tools、authorizing、awaiting_approval、executing、replanning、synthesizing。它不等于 `AgentRun.status`，只允许协调节点覆盖更新。

`plan` 至少包含 revision、goal 和不可变的 plan nodes：

- Planner 产生首个 revision，Replanner 产生新的完整 revision。
- State 只保存当前 plan；旧 revision 由 checkpoint history 保留，不另建 `plan_history`。
- plan node 定义准备执行的工作，不在并行 worker 中原地写执行状态。

### 6.5 node_outcomes 与幂等 reducer

每次节点逻辑执行返回一个 `NodeOutcome`，至少表达：

```text
plan_revision
node_id
logical_attempt
outcome
observation
retryable
tool_call_id
artifact_refs
evidence_refs
error_code
```

- `observation` 只保存短摘要；工具原始输入/输出仍在 M06。
- artifact/evidence 只保存稳定引用。
- reducer 使用 `(plan_revision, node_id, logical_attempt)` 作为稳定键。
- 新键加入；相同键且内容相同视为幂等重放；相同键但内容冲突必须报一致性错误。
- 合并后按稳定键排序，不能让并行完成先后影响最终 State。
- 不使用简单 `operator.add`，避免 checkpoint replay 或 worker 重试产生重复结果。
- 只有专门的协调/压缩节点可以显式整体替换 reducer channel；普通 worker 只能提交增量。

### 6.6 approval_wait（已确认）

每个顶层 `AgentRun` 同时最多有一个 active approval batch；一个 batch 可以包含当前执行波次中多个敏感工具操作。State 只保存 batch 的恢复定位信息：

```text
approval_wait
  approval_id
  plan_revision
  item_refs
    node_id
    tool_call_id
  requested_at
```

- M06 保存权威的 `ApprovalRequest` 与 `ApprovalItem`：至少包含 `approval_id`、`run_id`、状态、过期时间、`tool_call_id`、`operation_id`、工具版本、参数摘要、策略版本、风险摘要和逐项 decision。
- State 不保存 `approved=true` 作为授权事实；恢复时必须重新查询 M06，并由 M04/M06 重新确认 Actor、权限、sandbox 和审批有效性。
- 当前 approval batch 使用一次 LangGraph interrupt；用户可以全部批准、全部拒绝或逐项决定。
- 被拒绝的 item 不直接伪造工具失败；它形成结构化拒绝 `NodeOutcome`，由 Replanner 决定替代方案或终止。
- 参数摘要、工具版本、策略版本或 operation identity 发生变化时，旧 item 失效，必须创建新的 approval batch；后续 replanning 不能借用旧 batch。
- 批量审批完成后 run 回到 `queued`，由任意可用 worker 重新领取；不能假设原 worker 仍存在。
- 过期、owner 失效、权限变化或 run 取消时，M06 关闭 batch；客户端提交的 resume 值只触发重新查询，不直接改变授权事实。

### 6.7 final_answer 与 failure

`final_answer` 至少包含回答正文、artifact references 和 evidence references。`failure` 至少包含稳定 code、安全 message、retryable、failed node reference 和可空 source reference。

- Generator 独占写 `final_answer`，失败收敛节点独占写 `failure`。
- 两者互斥；同时存在属于 State 不变量破坏。
- State 不保存终态 status；`AgentRun.status` 根据图完成结果幂等对账。

### 6.8 Runtime Context 与现有字段替换

以下内容不进入 State/checkpoint，而通过 LangGraph config、`Runtime[RunContext]` 或权威服务获得：

- run/checkpoint/conversation identity；
- 从 M04 `RunGrant` 与当前策略交集派生的 `ExecutionAuthorization`；原 session 只作归因，凭据不进入 Runtime Context；
- 数据库、M04/M05/M06/M08 服务和模型实例；
- 当前权限、工具目录、sandbox policy；
- Prompt/ProjectionPolicy、ProjectionManifest；
- 完整对话历史、工具结果和 RAG 文档；
- cancel 请求和 `AgentRun.status`。

现有 `AgentState.messages` 后续由 M01 `ConversationMessage` 与 ContextProjection 取代；`pending_user` 由 `task_input` 取代；`turn_provenance` 由消息和 AgentRun 的稳定引用取代。M07 重构后，LangGraph invoke/stream 成为权威执行路径，不再由模型直调后使用 `update_state` 补投影。

## 7. AgentRun 与 ActiveRunContext（已确认）

### 7.1 命名替换

- 新的持久化执行模型命名为 `AgentRun`，替代讨论中暂用的 `RunRecord`。
- 进程内临时执行对象命名为 `ActiveRunContext`。
- 现有 `ConversationRun` 不再作为独立最终概念保留。
- 当前 `ConversationRun` 不能原样持久化，其中的 lease、token 等必须移入 `ActiveRunContext`。

### 7.2 AgentRun 的最小职责

`AgentRun` 至少表达：

- `run_id`、`conversation_id`、owner/tenant 归属及 `run_grant_id`；
- `input_message_id` 与可空 `output_message_id`；
- 对外生命周期 `status`；
- `runtime_contract_version`；checkpoint identity 由 `run_id` 推导；
- 取消请求与取消完成时间；
- 调度领取者、租约到期时间、基础设施执行尝试次数；
- retry 关系和触发方式；
- 创建、开始、更新和终止时间及稳定 reason code。

计划、节点状态、working messages、observations、工具结果和完整异常不放入 `AgentRun`。

### 7.3 外部 status 与图内 phase

两者明确分开：

- `AgentRun.status` 面向 API、列表、取消、调度和恢复资格。已讨论的生命周期集合为 `queued`、`running`、`waiting_approval`、`succeeded`、`failed`、`cancelled`、`incompatible`。最终命名仍可在 Shape 中校准，但不得混入具体节点名。
- State 的 `phase` 面向图内路由，例如 planning、authorizing、executing、observing、replanning、synthesizing。
- State 删除通用 `status` 字段，避免与 `AgentRun.status` 重叠。
- M07 负责 status 与 phase 的投影转换；M06 不直接修改 run 生命周期。

### 7.4 单活跃 run

- 同一个 conversation 同时只允许一个非终态顶层 `AgentRun`。
- `queued`、`running`、`waiting_approval` 都占用执行权。
- 并行能力放在一个 LangGraph run 内部。
- 成功、失败、取消或不兼容后释放执行权。
- 约束必须由持久化数据库保证，不能只依赖进程内 `ThreadLease`。

### 7.5 生命周期与 worker lease（已确认）

`AgentRun.status` 使用以下状态和转换：

```text
创建                         -> queued
queued + worker 原子领取      -> running
running + 需要人工审批         -> waiting_approval
waiting_approval + 审批已决    -> queued
queued + worker 再次领取       -> running
running + 正常完成             -> succeeded
running + 不可恢复失败          -> failed
queued/running/waiting_approval + 取消收敛完成 -> cancelled
queued/running/waiting_approval + runtime contract 不兼容 -> incompatible
```

- `succeeded`、`failed`、`cancelled`、`incompatible` 是不可逆终态；终态 run 不复活，用户重试创建新的 `AgentRun`。
- 不增加 `cancelling` 状态。取消请求通过 `cancel_requested_at` 和相关归因字段表达，run 保持原状态，直到图和 M06 事实安全收敛后进入 `cancelled` 或真实终态。
- 基础设施瞬时失败、进程崩溃或 worker lease 过期不创建新 run，也不构成用户重试；只在同一 run 上增加 `execution_attempt` 并恢复原 checkpoint。
- `failed` 只用于节点技术重试预算耗尽、图明确收敛为不可恢复失败或业务执行已无法继续；尚可由基础设施自动恢复的 run 不应提前写成 `failed`。
- `waiting_approval` 释放当前 worker lease，但继续占用 conversation 的单活跃执行权。
- 审批作出决定后先把 run 置回 `queued`，再由任意可用 worker 重新领取；不能假设发起 interrupt 的原 worker 仍然存在。
- running lease 过期时可以由新 worker 原子接管并递增 `execution_attempt`，无需先制造一个对外可见的 `queued` 中间状态。
- `execution_attempt` 同时作为 fencing token。旧 worker 提交 checkpoint 之外的业务更新、续租或终态时，必须携带并匹配当前 attempt/claim，防止租约过期后的迟到写覆盖新 worker。
- `execution_attempt` 只表达基础设施领取次数；用户重试使用新的 `AgentRun`，图内 `logical_attempt` 表达节点逻辑尝试，三者不得混用。

### 7.6 线性消息模型

VenAgent 当前最终目标不提供重新生成回答、切换回答版本或从旧回答分叉，因此不预建消息树能力：

- `ConversationMessage` 在 conversation 内使用单调递增的 `sequence` 形成线性历史。
- 不增加 `head_message_id`、`parent_message_id`、候选版本或分支表。
- `AgentRun.input_message_id` 与 `output_message_id` 已足够关联一次请求及其回答。
- 同一 user message 最多产生一个成功 assistant message。
- `ContextProjection` 按线性消息顺序选取上下文，不遍历祖先链或候选回答。

### 7.7 终态 reason code 与重试资格（已确认）

`AgentRun` 只保存终态原因，不持久化容易过期的 `retry_allowed` 布尔值：

```text
terminal_reason_code: string | null
terminal_message: safe display text | null
terminal_source_ref: stable reference | null
```

稳定 reason code 的最小集合为：

```text
failed:
  task_failed
  retry_exhausted
  infrastructure_unrecoverable
  finalization_failed

cancelled:
  user_requested
  owner_deleted
  thread_deleted
  security_revoked

incompatible:
  runtime_contract_mismatch
```

- `terminal_message` 只能是安全概括，不能保存异常栈、凭据或工具原始响应；节点级细节保存在 State `failure` 或 M06 权威记录中。
- `succeeded` 不需要失败 reason code；非终态也不写 terminal reason。
- `failed/task_failed`、`failed/retry_exhausted`、`failed/infrastructure_unrecoverable` 和 `incompatible/runtime_contract_mismatch` 原则上允许用户创建新的 retry run。
- `failed/finalization_failed` 只有在旧 run 的 checkpoint、assistant message 和 M06 事实完成对账后，才允许创建新的 retry run。
- `cancelled/user_requested` 原则上允许重试；`owner_deleted` 和 `thread_deleted` 不允许重试；`security_revoked` 只有 owner/权限重新有效后才能重新判断。
- `retry_eligible` 是 API 查询时根据终态、conversation/thread 生命周期、owner 权限、单活跃约束、最新未完成消息规则和 M06 对账结果计算的投影，不成为新的权威事实。
- 用户重试仍必须满足“原 user message 是当前 conversation 最新未完成消息”；不满足时只能发送新的 user message。

### 7.8 状态转换权限（已确认）

建立统一的 `AgentRunLifecycle` 应用服务作为 `AgentRun.status` 唯一业务写入口。调用方只能请求自己职责范围内的转换，所有转换均通过同一状态机校验、数据库 CAS 和 claim/fencing 检查：

| 转换 | 允许的发起方 |
|---|---|
| 创建 `queued` | Conversation command service，在 user message/run 原子创建事务中 |
| `queued -> running` | Scheduler claim |
| 过期 `running` 接管 | Scheduler recovery claim |
| `running -> waiting_approval` | Checkpoint reconciler，在确认 active interrupt 与 M06 batch 后 |
| `waiting_approval -> queued` | Approval resume service，在 M06 batch 已决后 |
| `running -> succeeded` | Finalizer，在最终 checkpoint 与业务发布不变量满足后 |
| `running -> failed` | Failure finalizer/reconciler |
| 非终态写取消请求 | Run control service，经 owner/系统权限校验后 |
| 非终态 `-> cancelled` | Cancellation reconciler，在 M06 事实收敛后 |
| 非终态 `-> incompatible` | Runtime-contract reconciler |

- HTTP route 只负责协议输入、身份解析和错误映射，不直接写 status。
- LangGraph 节点只返回 State 更新或 interrupt，不直接写 `AgentRun.status`。
- M06 只保存并返回工具、审批、安全和 operation 权威事实；由 reconciler 将这些事实投影为 run 生命周期。
- Scheduler 只负责领取、接管和续租，不能把任务或工具失败直接写成 `failed`。
- Finalizer 只能依据满足终态不变量的公开 checkpoint 状态写终态，不能根据流连接结束或内存标志猜测成功。
- 数据库负责枚举/check、外键、唯一性、单活跃 run 和 fencing 等约束；不使用复杂 trigger 承载业务状态机。
- 每次状态变化更新 `updated_at`，终态写对应完成时间与 `terminal_reason_code`；不为状态变化另建通用事件表。

### 7.9 RunGrant 与最小权限恢复（已确认）

worker 不代行 owner，也不获得 owner 的环境权限。worker 的服务身份只证明它是可信 VenAgent worker；实际数据和工具权限来自绑定单个 run、可撤销的最小权限委托 `RunGrant`：

```text
RunGrant
  grant_id
  run_id
  owner_id
  tenant_id
  conversation_id
  allowed_data_scopes
  allowed_action_classes
  authorization_epoch
  requested_by_session_id
  expires_at
  revoked_at
```

- M04 在 user message 与 `AgentRun` 原子创建事务中签发 RunGrant，并将 `grant_id` 关联到 run。
- RunGrant 只允许访问当前 conversation、经 M05 过滤的 owner memory scope、明确引用的 evidence/artifact，以及当前 run 的 artifact namespace；它只能向 M06 请求工具授权，不能直接执行任意工具。
- `requested_by_session_id` 只用于审计和请求归因，不成为恢复凭据；access/refresh token、Cookie、API key 和外部凭据不进入 RunGrant、AgentRun、State 或 checkpoint。
- worker 恢复时以服务身份领取 run，加载并验证 RunGrant 与 run/owner/tenant/conversation 绑定、`authorization_epoch`、过期和撤销状态，再派生进程内 `ExecutionAuthorization`。
- owner 删除、安全撤销或 tenant 失效时递增/失效授权 epoch，使旧 RunGrant 立即不可用；普通 logout 或 access session 过期默认不撤销已经创建的后台 run。
- guest RunGrant 的有效期不得超过 guest conversation 生命周期；run 终态、grant 撤销或 conversation 删除后不得继续使用。

每个真实工具操作仍由 M06 签发更窄的 operation authorization：

```text
OperationGrant
  grant_id
  tool_call_id
  tool_id
  tool_version
  arguments_digest
  resource_scope
  approval_id
  expires_at
```

有效权限始终取以下交集：

```text
RunGrant 权限上限
  intersect owner 当前权限
  intersect M06 工具策略
  intersect sandbox 策略
  intersect ApprovalItem 决策
```

- 缺少任意一项都不能执行；审批和 Prompt 不能扩大 RunGrant 权限上限。
- M06 在操作执行时通过 credential broker 获取当前有效凭据；OperationGrant 只保存凭据引用或授权结果，不返回明文。
- M01/M05/M06/artifact 等应用端口必须接收显式 `ExecutionAuthorization` 或 operation grant，不能仅凭 `owner_id` 查询 owner 的全部资源。
- ContextProjection 只接收脱敏 `IdentityView` 和能力可用性，不接收 grant 内容、credential handle 或凭据。
- owner/tenant 已删除或进入 deleting 时不得恢复，run 按删除/安全策略收敛；工具权限收窄但 run 仍有效时，由 M06 返回拒绝事实，交给 Replanner 或失败路径处理。

## 8. 取消、恢复与对账（已确认）

### 8.1 取消

- 取消请求以持久化 `AgentRun` 为权威。
- 进程内 cancel token 只提供快速通知。
- M07 在节点边界、恢复时和执行外部副作用前检查取消状态。
- 已发出的外部工具调用不能假装回滚；M06 继续记录其真实完成或失败结果。
- 工具执行期间取消时，先完成 M06 事实对账，再将 run 收敛为 `cancelled`。
- 等待审批的 run 被取消时结束等待，并使相应审批关闭或失效。

### 8.2 AgentRun 与 checkpoint 对账

不引入分布式事务或两阶段提交：

- 图暂停或完成时，先确保 checkpoint 成功，再更新 `AgentRun.status`。
- 取消请求反向先写 `AgentRun`，图随后读取并响应。
- 两次写入之间崩溃时，在启动、查询或恢复路径按 checkpoint 对账生命周期投影。
- 对账操作必须幂等，且不得篡改 M06 已发生的工具事实。

### 8.3 连接生命周期（已确认）

- SSE/HTTP 连接只承担实时传输，不拥有 `AgentRun` 生命周期。
- 网络断线、页面刷新、关闭页面或浏览器进程退出不自动取消 run；服务端继续执行或保持 `waiting_approval`。
- 只有用户显式取消、owner/thread 删除、身份或安全策略要求终止，以及服务端确定的不可恢复失败，才能请求 run 取消或收敛到相应终态。
- 客户端重新进入后，通过最小 run 状态查询或重新订阅协议恢复当前状态和最终结果。
- 不建设持久化 token delta 账本，因此重连不承诺补放断线期间的逐 token 输出；客户端至少能取得当前生命周期、等待审批信息以及成功后的最终 assistant message。
- 身份切换和 session 撤销触发的是独立的授权/取消政策，不能继续借由关闭 SSE 连接隐式表达。

### 8.4 最终完成事务与崩溃对账（已确认）

成功结果采用“LangGraph 最终 checkpoint 先完成，业务结果随后原子发布”的顺序：

1. LangGraph 写入最终 checkpoint。
2. finalizer 通过图公开状态接口确认图已经结束、没有 active interrupt，并包含满足不变量的 `final_answer`。
3. finalizer 使用当前 claim/fencing token，在一个业务数据库事务中锁定 `AgentRun`，插入 assistant `ConversationMessage`，写入 `output_message_id`，把 status 更新为 `succeeded`，更新 conversation 时间、标题和 TTL，并清理 claim/lease。
4. 业务事务提交后，HTTP/SSE 才能返回成功或发送 `completed`；连接传输不能先于业务发布宣告成功。

assistant message 与 `AgentRun.succeeded` 必须处于同一个业务数据库事务，并由数据库保证：

```text
assistant_message.source_run_id UNIQUE
assistant_message.reply_to_message_id UNIQUE
```

- 同一个 run 只能发布一条最终 assistant message；同一个 user message 最多拥有一条成功回答。
- finalizer 可以安全重放；唯一约束、终态不变量和 CAS 命中既有提交时返回原结果，不创建第二条消息。
- 最新 checkpoint 显示图结束且有 `failure` 时，事务只把 run 收敛为 `failed`，不创建 assistant message。
- 最新 checkpoint 存在 active interrupt 时投影为 `waiting_approval`；仍有下一节点时保持或恢复 `running`；runtime contract 不匹配时收敛为 `incompatible`。
- 业务代码只使用 LangGraph 公开的图状态/checkpointer 契约进行对账，不查询其私有物理表。

崩溃窗口按以下方式收敛：

- 最终 checkpoint 成功、业务事务前崩溃：run 保持非终态，恢复 worker 重新执行 finalizer。
- 业务事务成功、发送 SSE 前崩溃：查询返回既有 `succeeded` 和 assistant message，不重新执行模型。
- finalizer 重复执行：幂等返回既有结果。
- 业务数据库暂时不可用：保持非终态并等待恢复，不直接写 `failed`。
- checkpoint 缺少必需终态、违反 `final_answer/failure` 互斥或持续无法安全发布时，完成安全对账后进入 `failed/finalization_failed`。

取消和成功的竞态由业务数据库 CAS 决定：

- finalizer 事务先提交为 `succeeded` 时，后续取消返回既有终态，不修改消息或结果。
- `cancel_requested_at` 先成功写入非终态 run 时，finalizer 不发布 assistant message；先对账 M06 已发生事实，再收敛为 `cancelled`。
- 不允许 assistant message 已发布而 `AgentRun.status=cancelled`，也不允许 `AgentRun.status=succeeded` 却没有对应 output message。

### 8.5 Run API、SSE 与重连协议（已确认）

创建持久化 run 与建立实时连接分离：

```text
POST /api/conversations/{conversation_id}/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/stream
POST /api/runs/{run_id}/cancel
POST /api/runs/{run_id}/retry
POST /api/approvals/{approval_id}/decision
```

- `POST /runs` 在业务事务中创建 user message 与 `AgentRun(status=queued)`，返回 HTTP 202、`run_id`、`input_message_id` 和当前 status；它不等待模型，也不依赖 SSE 是否成功建立。
- 创建请求使用 `client_request_id` 幂等；重复请求返回同一个 message/run，不重新创建或启动任务。
- 客户端获得 `run_id` 后连接 `/stream`；SSE 连接断开、重连和数量都不改变 run 生命周期。
- `GET /api/runs/{run_id}` 至少投影 run/message identity、status、取消请求、终态原因、安全 message、动态 `retry_eligible`/拒绝原因、进度摘要、审批摘要和主要时间戳。
- run 查询只返回安全的 phase、完成节点数和总节点数等进度投影，不暴露完整 State、Prompt、工具参数、原始错误或 checkpoint 内容。
- 所有 run、retry、cancel、stream 和 approval 表面都按 owner 鉴权；不存在与跨 owner 访问使用同一安全错误，不泄露资源存在性。

SSE 新连接第一条业务事件始终为当前权威 `snapshot`，随后可发送：

```text
status
progress
token
approval_required
completed
failed
cancelled
incompatible
```

- `token` 只表示当前连接建立后观察到的实时增量，不建设断线 token replay，也不承诺 `Last-Event-ID` 历史补放。
- terminal run 建立连接时发送 snapshot 和相应终态事件后关闭；running/waiting run 可以被同一 owner 的多个客户端观察。
- SSE 不可用时，前端回退为定时查询 `GET /api/runs/{run_id}`；轮询和 SSE 读取相同的 run 投影服务。
- 断线前的 partial text 只是浏览器本地临时显示，可以保留并标记“后台继续”，但不能回写服务端或进入正式历史。
- 收到 `completed` 后必须用持久化 assistant message 完整替换 partial；失败、取消或不兼容时 partial 不成为 `ConversationMessage`；页面刷新可以丢弃 partial，只恢复 run 状态与最终结果。
- `/retry` 返回新的 `run_id`，不修改原 run，并执行最新未完成消息、owner 权限、单活跃 run 和 M06 对账检查。
- approval endpoint 只把逐项决策写入 M06，并由 approval resume service 把 run 置回 `queued`；客户端不能通过 SSE resume payload 直接授予权限。

## 9. 对话消息模型（已确认）

### 9.1 替换 TurnRecord

废弃现有成对 `TurnRecord(user_content, assistant_content)` 的最终语义，不做旧版本兼容。

- 用户请求通过校验后，立即持久化为不可变的 `ConversationMessage(role=user)`。
- 成功发布最终回答后，创建独立的 `ConversationMessage(role=assistant)`。
- `AgentRun.input_message_id` 指向用户消息。
- 成功后 `AgentRun.output_message_id` 指向该次 run 产生的 assistant 消息。
- assistant message 保存唯一 `source_run_id` 和 `reply_to_message_id`，分别约束一次 run 只能发布一次、一个 user message 最多有一个成功回答。
- 失败、取消、等待审批或不兼容不伪造 assistant 消息。
- UI 通过消息与 run 的投影展示完整时间线和失败/等待状态。

### 9.2 消息与模型上下文不是同一概念

数据库消息列表不是模型调用的直接上下文。`ContextProjection` 按策略选取：

- 已采用的近期成功对话；
- 当前用户请求；
- 与当前任务有关的失败/取消尝试摘要；
- M05 检索出的可访问记忆；
- State 中当前计划和执行摘要；
- M04/M06 实时返回的权限、工具、沙箱和审批状态。

M05 不能仅以 run 是否成功作为唯一提取标准；它应从被明确允许的消息和执行结果中提取，避免失败尝试自动污染长期记忆。

### 9.3 前端消息与运行投影（已确认）

前端保持一条线性对话，但不再把正式消息、运行状态和流式草稿合并为同一种 `Message`：

- `ConversationMessage` 只表示服务端已经持久化的真实 user/assistant 消息；发送请求时不得预先伪造一条 assistant message。
- 每个 user message 下方可投影其关联的 `AgentRun` 尝试。`queued/running` 显示内联运行区及安全的阶段、进度和取消操作；`waiting_approval` 在同一区域显示 approval batch 和逐项决策；`failed/cancelled/incompatible` 显示安全终态原因及动态可用的重试操作。
- 同一 user message 有多个未成功 run 时，默认折叠为“此前有 N 次尝试”，按需展开终态摘要；成功 assistant message 仍作为普通对话消息显示，不为每个 run 创建长期占据时间线的独立卡片。
- 流式 token 只进入浏览器内存中的 `PartialStreamState`，以 `run_id` 为键；它不是 `ConversationMessage`，不写入 `localStorage`，也不作为刷新或恢复依据。
- 收到 `completed` 后，客户端读取服务端已持久化的 assistant message 并完整替换 partial；断线、刷新或切换对话可丢弃 partial，但不能取消或篡改后台 run。
- conversation 详情查询返回线性 messages 和轻量 run summaries；run 详情、当前 approval 和实时进度继续通过 run 查询/SSE 获取。两者由同一后端投影契约关联，前端不得根据文本或相邻位置猜测 run/message 身份。
- Pinia 内部至少分离正式消息、`runsById` 和 `partialByRunId`，再由纯 selector 生成组件时间线。组件只渲染投影和发送命令，不直接合并权威事实。
- 页面加载、SSE 重连和轮询回退均先采用权威 snapshot；迟到 token、旧 run 事件和不匹配 `conversation_id/run_id` 的事件必须丢弃。终态后取消按钮、审批按钮和输入状态必须立即收敛，避免重复操作。

前端交互不是仅靠自动化测试即可验收的实现细节。最终 Verify 必须启动真实后端和实际前端，通过浏览器完成发送、流式显示、断线重连、刷新后恢复、后台完成、取消、失败重试、多个失败尝试折叠、逐项审批、终态替换、跨 owner 隔离和窄屏响应式流程；同时检查浏览器控制台、网络请求和重复消息/迟到事件。开发代理形态与 FastAPI 托管的生产构建形态都要覆盖关键路径。自动化测试、故障注入和截图是证据，但不能替代真实操作；验收发现影响正确性、可理解性或可操作性的问题时必须修复，并重新执行受影响流程后才可归档。

## 10. 用户重试与基础设施恢复（已确认）

### 10.1 重试身份与线性限制

- `ConversationMessage` 按用户真实发言次数创建。
- 只有用户明确执行“重试”，或 API 明确引用原 `message_id` 时，才复用原用户消息。
- 不得按文本内容相同自动复用或去重；用户再次发送相同文字仍是新消息。
- 明确重试始终创建新的 `AgentRun` 和 checkpoint 链。
- 原 run 保持原终态，不修改、不复活。
- 重试记录 `retry_of_run_id`。
- 修改请求后再发送属于新消息和新 run，不属于重试。
- 服务崩溃、worker 租约过期后的接管继续同一个 run，不属于用户重试。
- 成功 run 不被“复活”，也不产生候选回答版本。

补充约束：

- 只允许失败、取消或不兼容的 run 被用户明确重试。
- 只有当前 conversation 中最新一个未完成的 user message 可以复用原消息重试；其后只要已经出现其他 user message，就不再允许对旧消息创建原地重试 run。
- 用户要重新执行更早的失败任务时，应发送一条新的 user message，并可显式引用旧 run、旧 artifact 或旧任务目标；这属于新任务，不属于原消息重试。
- 当前不提供重新生成回答、切换回答版本或从旧回答分叉。
- 第一次成功后产生唯一 assistant 消息。

### 10.2 跨 run 事实复用与副作用保护

用户重试创建新的 `AgentRun` 和 checkpoint，但不能把“新 run”理解为允许无条件重做旧 run 已经发生的外部操作：

- 新 run 不继承或继续旧 checkpoint、旧 plan 和旧图内现场；它们只可作为诊断或输入摘要参考。
- 新 run 在执行相关工具前必须读取 `retry_of_run_id` 指向的旧 run，并查询 M06 的稳定工具事实、外部操作状态和 artifact references。
- 旧 run 已完成的外部副作用不得因创建新 run 而自动重复执行。
- M06 必须能表达新 `tool_call_id` 与旧 operation/tool call 的“延续、复用或重新执行”关系；具体字段名和表结构留到 M06 Shape 确定，不为此建设通用事件系统。
- read-only 工具可以重新执行或使用仍有效的缓存结果。
- 已完成的幂等操作应通过 M06 的稳定 operation identity 对账后复用；不能仅使用包含新 `run_id` 的幂等键判断为全新副作用。
- 已完成的非幂等操作默认引用旧结果并继续，或在确需再次执行时请求新的明确审批；不得自动重做。
- 外部调用结果未知时，必须先通过 M06 或目标系统对账为 completed、failed 或仍 in-flight，禁止盲目重试。
- 旧 artifact 通过稳定引用显式继承；新 run 不复制大段原始内容，也不能在无权或已失效时继续访问。
- RAG 默认按当前权限和索引重新检索；旧 evidence/artifact 只有在来源仍有效、权限重新通过且当前任务明确采用时才复用。
- 新 run 的 ContextProjection 应获得旧 run 的短摘要、可复用事实引用和风险标记，不直接注入旧 checkpoint 的全部 State。

## 11. 创建事务、幂等与调度（已确认）

### 11.1 原子创建边界

初次发送在同一数据库事务中：

1. 写入 user `ConversationMessage`；
2. 创建 `AgentRun(status=queued)`；
3. 占用 conversation 的单活跃执行权。

明确重试在事务中复用指定 `input_message_id`，只创建新的 `AgentRun` 并占用执行权。事务提交后才能交给 LangGraph；事务失败时不得启动任务。

### 11.2 API 幂等

- `client_request_id` 标识一次 API 操作，而不是天然等同于一条消息。
- 它在 conversation 范围内唯一。
- 相同 ID 重发返回同一次操作关联的 message/run。
- 相同 ID 携带不同操作、消息或目标 run 时返回幂等冲突。

### 11.3 调度接管

- 事务成功但尚未启动就崩溃时，run 保持 `queued`。
- 调度器以持久租约领取，至少表达 `claimed_by`、`claim_token`、`lease_expires_at` 和 `execution_attempt`。
- 租约过期后其他 worker 可接管并恢复同一 run/checkpoint。
- `execution_attempt` 是基础设施领取次数，不等于用户重试。

### 11.4 Claim、lease 与公平性基线（已确认）

默认配置采用：

```text
lease_duration_seconds = 60
heartbeat_interval_seconds = 15
claim_poll_interval_seconds = 2 + jitter
worker_run_concurrency = 2
owner_running_limit = 2
max_consecutive_no_progress_recoveries = 3
```

- 时间判断统一使用数据库 `now()`，不能以 worker 本机时钟决定 lease 是否过期。
- heartbeat 由独立后台任务执行，不依赖 LangGraph 节点结束；只在 `running` 且 claim 仍有效时续租。
- 进入 `waiting_approval` 或终态时立即释放 worker lease，但 `waiting_approval` 继续占用 conversation 单活跃执行权。
- `lease_expires_at <= database_now()` 时允许立即接管，不额外增加宽限期。
- 启动高风险外部操作前，如果 lease 剩余时间不足，worker 必须先成功续租。
- 领取时在一个数据库原子操作中更新 `claimed_by`、新的 UUID `claim_token`、`lease_expires_at` 和 `execution_attempt += 1`；首次领取同时把 `queued` 改为 `running`，过期接管保持 `running`。
- heartbeat、续租、checkpoint 之外的业务状态更新和终态提交都必须匹配当前 `run_id + claimed_by + claim_token + execution_attempt`；旧 attempt 的迟到写必须被拒绝。
- fencing 只能阻止旧 worker 修改 VenAgent 权威状态，不能撤回已经发出的外部操作；M06 仍以 operation identity 对账真实副作用。
- queued run 按稳定 FIFO `created_at, run_id` 领取；当前不提供 VIP、手动插队、aging 权重或任务类型优先级。
- 每个 worker 默认最多执行两个顶层 run，每个 owner 默认最多同时拥有两个 `running` run；具体值可配置，不能写死在领域逻辑中。
- 顶层 run 并发由调度器限制，run 内 LangGraph 节点并行由 M07 限制，工具/sandbox 并发由 M06 限制，数据库连接池由基础设施限制，四者不能合并成一个计数器。
- 当前不建设独立消息队列；`AgentRun(status=queued)` 本身作为待领取集合，M09 再根据真实吞吐需求扩展队列与优先级。

基础设施恢复预算不直接使用 `execution_attempt`：

- 新 attempt 产生新的有效 checkpoint 进展时，连续无进展计数清零。
- worker 再次丢失且没有任何 checkpoint 进展时，连续无进展计数加一。
- 连续三次无进展后，run 收敛为 `failed/infrastructure_unrecoverable`。
- `waiting_approval -> queued -> running` 和正常的 checkpoint 后接管不计为无进展失败。

数据库或持久化 claim 能力不可用时 fail closed：

- 停止领取新 run，也不启动新的模型调用或外部工具副作用。
- heartbeat 失败后，当前进程的 `ActiveRunContext` 进入临时 `lease_uncertain`；该状态不写入 `AgentRun.status`。
- 已发出的外部调用可以自然完成，但其结果不能绕过 claim/M06 对账直接提交为权威事实。
- 数据库恢复后重新确认 claim token；claim 已丢失时，旧 worker 丢弃迟到业务写，由当前 worker 通过 M06 operation identity 对账。
- 数据库故障本身不直接把 run 标成 `failed`；持久状态等待恢复、lease 接管或达到已确认的无进展恢复预算后再收敛。

## 12. 不建设通用 AgentRunEvent（已确认撤回）

此前曾提出新增 `AgentRunEvent`，随后确认该问题与已有决定重复，因此撤回：

- 不新增通用 `AgentRunEvent` 表。
- checkpoint/history 承担图内快照和 super-step 历史。
- `AgentRun` 保存当前业务生命周期和关键时间戳。
- M06 保存工具、审批与安全事实。
- SSE 是实时传输，不建设持久化 token delta 账本。
- 将来只有出现明确的跨设备可靠业务事件重放需求时，才单独评估 outbox 或领域事件；现在不预建。

## 13. 明确排除项（已确认）

- 不兼容旧 checkpoint、旧 Graph 或旧 `TurnRecord` 数据模型。
- 不编写旧版本迁移器。
- 不让业务 API 查询 LangGraph checkpointer 私有表。
- 不把工具原始结果、审批或安全事实复制到 State/AgentRun。
- 不把动态 Prompt 当作权威状态。
- 不引入分布式事务、两阶段提交或通用事件溯源系统。
- 不为未来未确认能力预建空壳。
- 当前阶段不创建 Comet change，不修改现有 spec，不开始实现。

### 13.1 数据保留与删除（已确认）

默认保留策略为：

| 数据 | 默认保留 |
|---|---|
| `ConversationMessage` | 随 conversation 保留，删除 conversation 时删除 |
| `AgentRun` 薄记录 | 随 conversation 保留 |
| 非终态 checkpoint | 必须保留，不设普通 TTL |
| 终态 checkpoint | 终态后 7 天 |
| M06 operation identity、结果状态和摘要 | 随 AgentRun/conversation 保留 |
| 工具原始大响应、stdout/stderr | 默认 7 天 |
| Approval 决策和安全摘要 | 随 AgentRun 保留 |
| 普通 artifact | 随 conversation 保留 |
| 明确标记的临时 artifact | 默认 7 天 |
| ProjectionManifest/诊断日志 | 默认 7 天，可由部署配置调整 |

- M06 的 operation identity、外部效果状态和摘要不能与原始工具输出一起短期删除，否则延迟重试无法判断外部副作用是否已发生。
- 终态 checkpoint 删除后，AgentRun、消息、M06 事实和 artifact 不受影响；旧 run 不再支持内部时间旅行或图现场诊断，用户重试仍创建新 run。
- guest 仍使用 7 天生命周期，只有成功发布 assistant message 才推进 `last_successful_at`；user message 创建、失败、取消和等待审批不刷新 TTL。
- guest 到期时删除 thread、run、checkpoint、M06 事实和 artifact；active 或 waiting run 先取消并完成对账，不在执行中直接删除。

旧版本不兼容采用显式 schema 重建，而不是旧数据转换器：

1. 普通启动发现旧 schema 时 fail closed，不自动执行 DDL。
2. 维护命令取得 advisory lock 并停止 VenAgent 写入。
3. 通过 LangGraph 公开 `delete_thread` 清理旧 conversation checkpoint。
4. 删除旧 `conversation_turns` 和旧 checkpoint-version 语义，不转换旧 turn。
5. 创建 `conversation_messages`、`agent_runs` 及单活跃、唯一性、owner 外键等新约束。
6. 结构仍兼容的 owner/user/session 表可以保留；不兼容业务数据不迁移。
7. 记录新 schema 版本后，durable 模式才允许启动。

conversation/owner 删除使用以下幂等顺序：

```text
标记 deleting
  -> 拒绝新 run 和读取
  -> 请求取消非终态 run
  -> 关闭 approval，完成 M06 副作用对账
  -> 删除每个 run 的 checkpoint
  -> 删除临时/普通 artifact
  -> 删除 M06 事实、AgentRun、ConversationMessage
  -> 删除 conversation/thread
```

任一步失败都保持 `deleting` 且由维护任务继续；半删除对象不得重新对用户可见。

## 14. 尚待继续讨论

以下内容尚未在本轮形成最终决定，后续应逐项讨论并直接更新本文：

- 模块重构顺序及这些决定分别落入 M01、M03、M04、M05、M06、M07 的哪个 change；
- 与当前已批准 Comet specs 的冲突清单和替换策略。

## 15. 后续进入 Comet 的条件

只有当上述未决项讨论完成，并由用户明确要求进入 Comet 时，才执行：

1. 重新运行 ambient resume probe；
2. 按项目规则 new/select Native change；
3. 执行模块 intake，审计当前 VenAgent、相关 AGI-saber 行为参考与官方 LangGraph 契约；
4. 将本文作为讨论输入，而不是未经复核直接复制成 spec；
5. 在 Shape 中建立决定到模块、接口、State、数据库、API、UI 和测试的追踪关系；
6. 获得 Shape 批准后才进入 Build。

进入 Comet 前还必须核对本文与当前代码及 `docs/comet/specs/` 的差异；讨论决定优先表达目标方向，但不自动覆盖现有已批准规格。

## 16. 2026-08-02 全局架构复审

### 16.1 审计结论

本次复审确认，`ConversationMessage + AgentRun + LangGraph State/checkpoint + ContextProjection` 四层模型的总体方向成立。State 与 Prompt 的职责划分只是其中一部分；真正决定后续重构能否稳定落地的，还包括业务事实、执行生命周期、持久化身份、并发控制、安全授权、重连、迁移、删除和 UI 投影。

当前不能把这些决定仅作为 M07 的内部重构。它们会直接替换 M01--M04 已批准规格中的下列现有契约：

- conversation `thread_id` 同时作为 LangGraph checkpoint 身份；
- `conversation_turns` 成对保存成功 user/assistant，并作为 checkpoint 修复权威；
- `ConversationRun`、`ActiveRun` 和 `RunRegistry` 只存在于当前进程；
- 客户端断线取消运行，完成后的 run ID 不可查询或恢复；
- 当前 M04 只保证单 API 进程内的 run、lease 和清理一致性。

因此，后续进入 Comet 时必须先形成一组跨 M01--M04 的运行身份与持久化基础契约，再让 M05、M06、M07 建立在新契约上。不能让旧的 conversation checkpoint 模型和新的 per-run checkpoint 模型长期并存。

### 16.2 除 State/Prompt 之外的问题域

#### A. 业务身份与命名

- 已确认业务对话统一命名为 `conversation_id`，一次执行使用 `run_id`；业务模型、数据库、API、前端和业务日志不再使用 `thread_id` 表达 conversation。
- LangGraph config 的框架字段 `thread_id` 只在 adapter 层出现，值恒等于 `run_id`；业务代码不得把 run checkpoint 误当成 conversation 历史。
- `checkpoint_thread_id` 不持久化，由 `run_id` 推导，避免重复字段漂移。
- 当前 `/api/threads`、`ThreadRecord`、`ThreadStore` 和前端 `threadId` 在跨 M01--M04 基础契约替换时统一重命名，不建设兼容别名或双写路径。

#### B. AgentRun 生命周期与控制面

- 状态集合、转换、不可逆终态、取消请求表达、终态 reason code、用户重试资格、基础设施恢复预算和转换权限已经确认。
- 单 conversation 只能有一个非终态顶层 run，必须由数据库约束或可证明的原子协议保证，不能继续只靠进程内 `ThreadLease`。
- 取消请求以持久化 `AgentRun` 为权威；cancel token 只能缩短当前进程的响应时间。
- `waiting_approval` 仍占用 conversation 执行权但释放 worker lease；审批已决后回到 `queued`，等待任意 worker 重新领取。

#### C. 持久化、调度与恢复

- 已确认使用数据库原子领取、60 秒 lease、15 秒 heartbeat、UUID claim token 与 `execution_attempt` fencing；queued run 采用稳定 FIFO，并设置 worker/owner 默认并发上限。
- claim/lease、无 checkpoint 进展恢复预算和数据库故障 fail-closed 属于 M07 前置基础，不应在 M07 中作为隐藏实现细节临时补入。
- 多 worker 扩缩容、复杂队列和优先级仍留到 M09；M07 前只实现已确认的最小持久领取、过期接管和 checkpoint 对账。
- checkpoint 保存图内现场，`AgentRun` 保存外部生命周期；两者之间不做分布式事务，而通过可重复的 reconciliation 收敛。

#### D. 断线、重连与结果获取

- 已确认网络断线、页面刷新或关闭页面不自动取消 run；这将替换当前前端和服务端把流断开视为运行中断的行为。
- 必须提供最小的 run 查询或重新订阅表面，使客户端能重新获得 `running`、`waiting_approval`、终态和最终 assistant message。
- 不建设 token delta 账本意味着重连时不保证逐 token 补放；可以读取当前持久状态和最终结果，但这个产品承诺必须明确。
- 用户显式取消、页面关闭、网络抖动、身份切换和 session 撤销不能继续共用一个模糊的“中断”语义。

#### E. 消息、重试与线性时间线

- `ConversationMessage` 逐条不可变保存是正确方向，但失败/取消 user message 是否进入跨设备历史、是否参与标题和记忆提取，需要独立政策。
- 复用旧 user message 创建新 run 时，如果其后已经有其他 user/assistant message，新的回答会在时间线上晚于后续对话，破坏“一个 user 后接一个 adopted assistant”的线性语义。
- 已确认只允许重试最新未完成 user message；其他旧请求如需再次执行，应创建新的 user message，并可显式引用旧 run 或 artifact。
- guest TTL、thread `updated_at`、自动标题和 M05 提取不能因失败消息的立即持久化而被无意推进。

#### F. 审批、工具副作用与幂等

- LangGraph 从 interrupt 恢复时会从包含 interrupt 的节点开头重新执行，interrupt 前创建审批、写审计或发起外部副作用必须幂等，最好拆成独立节点。
- M06 的工具幂等键应至少包含 `run_id + plan_revision + node_id + logical_attempt`，防止不同 plan revision 的同名节点碰撞。
- crash 发生在 M06 已完成工具调用、但 M07 尚未写入 `node_outcomes` 时，恢复必须通过相同幂等键读取 M06 的既有事实，而不是再次执行副作用。
- 用户重试产生新 run 时，M06 仍必须沿 `retry_of_run_id` 对账旧 operation；新 `run_id` 不能成为重复执行已完成副作用的理由。
- `approval_wait` 使用单值 batch 引用；batch 内逐项审批，拒绝项通过 `NodeOutcome` 进入 Replanner。

#### G. 身份、安全与恢复授权

- 已确认 worker 不代行 owner；M04 为单个 run 签发可撤销 RunGrant，恢复时派生最小 `ExecutionAuthorization`，M06 再为具体操作签发 OperationGrant。
- `AgentRun` 持有 owner/tenant、请求归属和 `run_grant_id`；恢复重新确认 owner active、authorization epoch、当前权限、工具可用性、sandbox 和审批有效性。
- session ID 只用于归因，普通 logout/session 过期不自动取消后台 run；owner 删除、安全撤销、tenant 失效和 guest 生命周期可以使 grant 失效并触发收敛。
- Prompt 中的权限和工具约束只用于模型引导，不能扩大 grant；M06 在真正执行前仍须重新授权和校验。

#### H. ContextProjection 输入一致性

- 已确认由 agent runtime/M07 的无状态 `ProjectionInputCollector` 按 typed provider 采集本次模型调用输入；它不保存快照、历史或恢复状态。
- LangGraph checkpointer 是唯一任务快照/回滚机制；Collector 只一次性取得带版本、时间戳和来源引用的当前视图，不表示 M04/M05/M06/M08 共享数据库事务。
- ContextProjection 保持纯函数；Collector 负责身份优先的调用顺序、默认超时、强制来源 fail closed 和可降级来源标记。
- M08 在 M07 之后实现，因此 M07 的投影输入只能把 Evidence 作为可选能力，不能提前创建无行为的 M08 空壳或硬依赖。
- 安全相关外部事实即使进入了本轮快照，工具执行前仍要再次确认，不能用投影一致性替代执行时授权。

#### I. 数据模型、迁移与清理

- 已确认不迁移旧 checkpoint 语义、不保留旧 Graph、不转换旧 `TurnRecord`；使用显式 schema 重建，普通启动遇到旧 schema fail closed。
- 新结构至少涉及 `conversation_messages`、`agent_runs`、单活跃 run 约束，以及 M06 的工具/审批/审计事实。
- 旧 checkpoint 通过 LangGraph checkpointer 公开 API 清理，不操作私有物理表。
- owner/thread 删除先不可访问，再取消和收敛 run、关闭 approval、清理 per-run checkpoint 与 M06 事实，最后删除业务行。
- 已确认不同数据类型的保留期与幂等维护顺序；M06 operation identity 与效果摘要随业务事实保留，原始大响应和终态 checkpoint 默认 7 天。

#### J. API、SSE 与前端投影

- 前端不再能只从 committed turn 判断历史；它需要把 `ConversationMessage` 与 `AgentRun` 投影成发送中、运行中、等待审批、失败、取消、不可兼容和成功状态。
- 已确认使用“创建 run 返回 202，再按 `run_id` 查询或连接 SSE”的协议，并提供显式 retry、cancel 和 approval decision 表面；它将替换当前连接即执行的 `POST /api/chat/stream` 模型。
- SSE 继续只承担实时传输，不承担业务真相；连接存在不等于 run 存在，连接结束也不应自动决定 run 终态。
- 不建设通用 `AgentRunEvent` 后，跨设备只能可靠读取当前状态、关键时间戳和最终消息，不能承诺完整中间事件重放。

#### K. 可观测性与验证

- `ProjectionManifest`、checkpoint history、AgentRun 状态和 M06 审计各自观察不同层面，日志和 LangSmith trace 需要用 `run_id`、`tool_call_id` 等稳定 ID 关联。
- 必须测试创建事务后崩溃、工具完成后崩溃、checkpoint 成功后状态未更新、assistant message 提交中断、lease 过期接管和 interrupt 恢复等故障窗口。
- 还需覆盖跨 owner 查询/取消/审批、session 撤销、删除与恢复竞态、旧 runtime contract 不兼容，以及前端断线后的状态恢复。

### 16.3 State schema 内部冲突

本文 3.2 仍列出了通用 working messages、observations 和 artifact references，而 6.3 的最终 State schema 已明确不保留通用 `working_messages`，并由 `node_outcomes` 统一关联 observation、artifact、tool 和 evidence 引用。

审计建议以 6.3 为最终方向：

```text
RunState
  task_input
  phase
  plan
  node_outcomes
  approval_wait
  final_answer
  failure
```

特定子图若确实需要消息循环，使用子图私有 State；不要把通用 working messages 重新放回顶层 RunState。该建议仍需用户明确批准后，才能回写 3.2 的已确认描述。

### 16.4 修正后的实施顺序（审计建议，待批准）

1. **运行身份与持久化基础**：协调替换 M01--M04 中的 `TurnRecord`、进程内 run、conversation checkpoint、断线和删除契约；引入 `ConversationMessage`、持久化 `AgentRun`、单活跃约束、最小 claim/lease、run 查询与对账。
2. **LangGraph 执行基础**：checkpoint 按 `run_id` 隔离，Graph invoke/stream 成为权威执行路径，建立 runtime contract version、取消检查、恢复和终态收敛。
3. **ContextProjection 基础**：实现无状态 `ProjectionInputCollector`、`ContextBlock`、角色级策略、token budget、manifest 与 fail-closed/degraded 规则，但不提前实现未到路线模块的业务能力。
4. **M05 长期记忆**：在新的消息、owner 和投影端口上实现检索与提取政策。
5. **M06 工具/沙箱/审批/审计**：建立执行授权、幂等工具事实、审批协议和 artifact 边界。
6. **M07 LangGraph 任务图**：实现 Planner、并行执行、Tool Selector、Replanner、Generator、interrupt/resume 与 checkpoint 恢复。
7. **M08 RAG**：接入可选 EvidenceContext 和引用投影。
8. **M09 扩展调度**：在已存在的最小 claim/lease 上增加真正的多 worker 扩缩、队列策略和吞吐治理。

该顺序不要求为讨论另建一个永久业务模块，但要求在首个相关 Comet change 的 Shape 中，把跨 M01--M04 的规格替换视为正式前置能力，不能只在 M07 内部悄悄改变。

### 16.5 当前可以确认与仍不能确认的内容

可以确认：

- 四层总体模型方向正确；
- per-run checkpoint、持久化 AgentRun、M06 权威工具事实和每次模型调用独立 ContextProjection 的边界正确；
- 不建设回答分支、通用 `AgentRunEvent`、第二套状态系统或 checkpointer 私有表依赖是合理的最小边界；
- 后续重构必须先调整运行持久化基础，再推进 M05/M06/M07。
- 前端采用线性正式消息加关联 run 尝试的投影；approval、失败、取消、重试和 partial 均不伪装成持久化 assistant message，并以真实浏览器交互作为最终验收门槛。
- 首个 Comet change 采用 `agent-runtime-foundation` 端到端基础纵切：统一业务身份和消息模型、持久化 `AgentRun`、claim/lease/fencing、最小 per-run LangGraph checkpoint 与 finalizer、最小 `RunGrant`、新 API/SSE、前端消息/run 投影和基础 `ProjectionInputCollector`；其 ProjectionPolicy 起点与扩展规则遵循 3.11 的暂定契约，归档时必须仍能真实完成发送、后台运行、重连、回答、取消和重试。
- 第二个 change 采用独立的 `memory-context`（M05）：只为实际消费记忆的 `GeneratorPolicy` 注册 `profile_memory`、`recalled_memory` 与可修订 `MemorySelection`，完成记忆检索、提取、owner 隔离、降级和真实跨对话验收；不实现工具、审批、Planner/Replanner、RAG 或其占位区段。
- 第三个 change 采用 `tool-aware-agent-graph`，将 M06 与 M07 作为同一用户可验收纵切交付，但保持模块代码所有权分离：M06 持有工具、sandbox、OperationGrant、幂等执行、审计和 approval batch；M07 持有 Planner、Tool Selector、观察、Replanner、Generator、interrupt/resume 与 State。该 change 必须以真实前端完成工具选择、授权、逐项审批、执行、重规划、断线恢复和副作用幂等验收；不提前接入 M08 evidence provider。
- 第四个 change 采用独立的 `rag-evidence`（M08），在工具任务图可用后实现知识源授权、索引、检索、引用和删除清理，并为真实消费者注册 `EvidenceContextProvider` 与可修订 `EvidenceSelection`。证据以有来源的 evidence block 进入上下文，不得冒充 System Prompt 指令或与 M05 记忆混合；evidence-required 节点失败时不得静默降级。归档前必须真实验收授权引用、无关内容抑制、owner 隔离、检索故障处理和删除后不可检索。
- M09 作为全部核心重构完成后的最终、按需 `scheduler-scale` 收尾 change；不阻塞 foundation/M05/M06-M07/M08 的完成，只在真实吞吐或多 worker 需求出现后扩展能力分组、owner 公平性、优先级、容量治理和调度观测。它只能扩展既有 claim/lease/fencing，不能重写 `AgentRun` 生命周期、checkpoint、RunGrant、M06 幂等或最终发布协议；启动时需以至少两个独立 worker 真实验收公平领取、崩溃接管、迟到写拒绝、副作用不重复、数据库故障停领和前端状态一致性。

当前讨论范围内没有剩余架构决策。实现前仍须在各 change 的 Comet Shape 中审计当时仓库和逐条形成实际 spec 文本；这不是重新开放已确认的权威边界，而是把暂定策略、当前代码和验收事实落为可验证契约。

### 16.5.1 Canonical specs 冲突矩阵（已确认）

下表仅决定 canonical `docs/comet/specs/` 的处理归属。`docs/comet/archive/` 保留为历史证据，不删除、不承担当前行为定义，也不构成旧 API、数据或运行语义兼容承诺。

| 现有 canonical spec | 处理 | 负责 change / 原因 |
|---|---|---|
| `conversation-context` | 整体替换 | `agent-runtime-foundation`：`conversation_id`、`ConversationMessage`、per-run checkpoint 和新 State 取代 thread、`messages/pending_user`、五轮窗口与 InMemorySaver 目标。 |
| `streaming-run-lifecycle` | 整体替换 | `agent-runtime-foundation`：创建 run 后订阅、持久 `AgentRun`、断线不取消、查询/轮询回退和新 SSE snapshot 取代 `POST /api/chat/stream`、仅内存 active run 与断线即取消。 |
| `conversation-persistence` | 整体替换 | `agent-runtime-foundation`：逐条 message、AgentRun、per-run checkpoint、finalizer/reconciler 和新删除/保留协议取代成对 turn、五轮 checkpoint 投影和从 turn 重建 checkpoint。 |
| `ownership-lifecycle` | 大幅替换并保留身份安全规则 | `agent-runtime-foundation` 保留 JWT/session/owner 隔离、Origin/CORS、删除不可访问等安全目标；替换 thread/turn/run、checkpoint 修复、历史、删除及“普通 logout/session 失效取消 run”等冲突语义。 |
| `frontend-foundation` | 保留技术基线、替换聊天状态契约 | `agent-runtime-foundation` 保留 Vue/Vite/Pinia、代理和部署基线；用正式 message、run summary、内存 partial、重连和审批投影取代 assistant 草稿、旧 stream 和 thread 缓存语义。 |
| `feature-first-package-layout` | 保留依赖方向、修订对象职责 | `agent-runtime-foundation` 保留业务不依赖 adapter 的边界；删除对 `threads.py`、进程 RunRegistry、legacy import、同步/旧流式 runtime 等具体旧职责的预设。 |
| `refactor-roadmap` | 整体替换 | `agent-runtime-foundation` 重写为 foundation → `memory-context` → `tool-aware-agent-graph` → `rag-evidence` → 按需 `scheduler-scale`，并纳入 3.11 的可修订 ProjectionPolicy 契约。 |
| `minimal-agent-loop` | 退休为历史基线 | 单节点、单轮、无持久化的“完整目标”不再是 canonical 目标；保留 archive 追溯，不保留运行兼容层。 |
| `bounded-chat-payloads` | 定向修订 | 保留输入/输出大小保护；由 foundation 更新五轮、旧 loop、旧流终态与提交语义引用。 |
| `infrastructure-startup-reporting` | 定向修订 | 保留统一启动报告与安全文案；更新 durable/temporary 能力描述及新运行时组件状态。 |
| `real-llm-adapter`、`llm-runtime-configuration`、`configuration-management`、`backend-ecc-audit`、`code-writing-standards`、`documentation-language-zh`、`ecc-lightweight-governance`、`skill-orchestration` | 保留 | 未发现对旧 thread、turn、checkpoint 或 SSE 语义的直接依赖；后续仅在存在实际引用时做最小联动更新。 |

`agent-runtime-foundation` 的 Shape 必须先完成表中前八项与两项定向修订的逐条旧条款到新条款映射，才可进入 Build。M05、M06/M07、M08、M09 分别在自身 Shape 中新增或修订真实模块规格，不将未来 provider、角色或 UI 空壳倒灌到 foundation。

### 16.6 实现注释要求（已确认）

后续 Build 在下列非显然边界必须添加简洁的原因型注释，说明“不变量、重放风险或为何需要该顺序”，而不是复述代码：

- claim token、`execution_attempt`、CAS 与 fencing 如何拒绝旧 worker 迟到写；
- LangGraph interrupt 恢复会重跑节点，因此 interrupt 前的 M06/审批操作为何必须幂等；
- 用户 retry 创建新 run 时，为何仍要沿 `retry_of_run_id` 对账旧 operation 并禁止重复副作用；
- 最终 checkpoint、assistant message、`AgentRun.succeeded` 与 SSE `completed` 的固定提交顺序；
- `lease_uncertain` 期间为何不能启动新的模型调用或工具副作用；
- SSE token/partial 只是传输态，为何不能进入 `ConversationMessage` 或作为恢复依据；
- Prompt 中权限/工具限制只是投影，为何 M06 执行前仍要重新授权；
- RunGrant、owner 当前权限、M06/sandbox 与 ApprovalItem 为何必须取交集，以及 worker 服务身份为何不能直接访问 owner 数据；
- reducer 的稳定键、幂等重放和冲突检测为何不能使用简单列表追加。

普通赋值、清晰的状态判断、类型声明和显而易见的 API 映射不添加叙述性注释；注释应随不变量测试一起维护，避免与实现漂移。

### 16.7 实施计划与意外预案门槛（已确认）

进入具体 Build 前，Comet Shape 必须产出逐模块、逐接口和逐数据面的可执行计划，至少包含：

1. **影响面清单**：列出当前 M01--M04 spec、Python model/port/service/adapter、PostgreSQL migration、LangGraph config、HTTP schema/route、Vue store/component、测试、运行命令和文档中所有 `thread_id`、`TurnRecord`、`ConversationRun`、conversation checkpoint 与进程内 run 依赖。
2. **规格替换矩阵**：逐条标记现有 `docs/comet/specs/` 契约是保留、替换还是删除，并指向新的 `ConversationMessage`、`AgentRun`、RunGrant、per-run checkpoint、API 和删除不变量。
3. **维护窗口准备**：确认没有需要保留的非终态旧 run，取得 advisory lock，停止写入，验证回滚快照可读，再开始旧 checkpoint 清理和 schema 重建。
4. **领域与数据库切换**：先建立新 schema/约束和 repository contract，再替换 conversation/run 用例；不保留旧 turn、新 message 双写或双读。
5. **LangGraph 切换**：通过唯一 adapter helper 固定 `thread_id=run_id`，Graph invoke/stream 成为权威执行路径，并验证 interrupt、checkpoint、恢复和 finalizer。
6. **授权与工具切换**：接入 RunGrant/OperationGrant、M06 operation identity、approval batch、credential broker 与删除/撤销路径后，才允许真实工具执行。
7. **HTTP/SSE 与前端切换**：后端新 `/api/conversations` 和 run API、前端 store/router/component、重连/partial 逻辑作为一个协调发布面验证，不允许前后端协议版本错配进入可用状态。
8. **旧代码清除**：新路径验证后删除 `ThreadRecord`/`TurnRecord`/`ConversationRun`/旧 RunRegistry、conversation checkpoint 修复和 `/api/threads` 旧表面；不得留下双权威备用路径。
9. **分层验证**：运行领域状态机、数据库竞态、LangGraph 恢复、M06 副作用、HTTP/SSE、owner 隔离、Vue 重连和端到端故障注入测试，并记录实际证据与剩余风险。
10. **真实交互验收**：启动真实后端以及开发代理和 FastAPI 托管两种前端形态，用浏览器操作关键用户流程并检查控制台、网络、响应式布局和状态收敛；发现问题后修复并重验，不能以自动化测试通过代替产品验收。

具体实现必须预先定义以下异常处理：

| 意外情况 | 预案 |
|---|---|
| advisory lock 或停止写入失败 | 不执行清理/DDL，保持旧 schema，报告占用者 |
| 旧 checkpoint 枚举或公开删除失败 | 不推进 schema version，不删除旧业务表；修复后幂等重跑 |
| DDL/约束创建失败 | 事务回滚，migration version 不前进，durable 启动继续 fail closed |
| 发现未知旧数据或孤儿记录 | 停止迁移并生成计数/安全诊断；不得猜测 owner 或自动绑定 |
| 新旧后端/前端协议不一致 | readiness 失败，不开放聊天入口；协调回退到同一版本组合 |
| `conversation_id`/LangGraph `thread_id` 映射错误 | 中央 helper 和契约测试阻断；不得在调用点手写 config |
| worker 迟到写或 lease 竞争 | claim token、execution attempt、CAS/fencing 拒绝并由 reconciler 收敛 |
| 工具调用结果未知或重复风险 | 停止后续副作用，通过 M06 operation identity 对账或重新审批 |
| RunGrant/owner/tenant 在恢复时失效 | fail closed，禁止数据/工具访问，按安全或删除 reason 收敛 |
| 最终 checkpoint 与业务发布中断 | finalizer/reconciler 幂等补交；在业务事务前不发送 completed |
| Build 后必须回退 | 不编写不可靠 down migration；恢复维护前数据库快照并部署匹配的旧代码 |

以下任一条件满足时必须停止 Build/迁移并保持 fail closed，不以临时兼容绕过：

- 现有 spec 冲突尚未在 Shape 中逐条解决；
- 回滚快照未建立或未验证可恢复；
- 仍存在无法安全取消/清理的旧活跃 run；
- checkpoint 公共清理未完成；
- schema lock、版本或约束验证失败；
- owner 隔离、fencing、副作用幂等、最终发布或删除竞态测试失败；
- 前后端对新 API、终态和重连语义的契约测试不一致；
- 真实浏览器验收仍存在重复消息、错误终态、不可恢复交互、越权信息、关键控制不可操作或响应式遮挡等问题。

该计划必须在 Comet Shape 中细化为可追踪任务、文件范围、验收条件、故障注入点和回滚检查表，经批准后才进入 Build；实现中遇到未覆盖的高风险状态时返回 Shape 重新决策，不临时扩张权限或引入兼容分支。
