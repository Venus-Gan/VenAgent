# Agent Runtime 完整目标规格

## 1. 四层职责

VenAgent SHALL 使用四个互不替代的层次：

| 层 | 权威职责 | 不承担 |
|---|---|---|
| `ConversationMessage` | 用户与最终助手的正式业务消息 | 图执行现场、流式 partial、工具事实 |
| `AgentRun` | 对外生命周期、查询索引、claim/取消/终态 | 节点现场、Prompt、工具审计 |
| LangGraph State/checkpoint | 单个 run 可恢复的图内现场与 super-step历史 | 对外业务状态、长期记忆、权限权威事实 |
| `promptctx ContextProjection` | 某次模型调用的角色专用输入投影 | 持久状态、授权、恢复或审计 |

进程内 `ActiveRunContext` 只容纳当前 claim/lease状态、cancel快速通知、`ExecutionAuthorization`、模型/服务句柄和实时观察资源；它不持久化，也不是恢复依据。

## 2. Runtime identity 与 contract

- 每个 AgentRun拥有独立 checkpoint链。唯一 adapter helper SHALL 映射 LangGraph `thread_id=run_id`，并携带 `runtime_contract_version`。
- Graph拓扑、顶层 State schema或节点结构化输入输出发生破坏性变化时递增 contract version；Prompt文案或 ProjectionPolicy单独版本化，不因此改 runtime contract。
- 恢复时 contract不匹配不得猜测迁移或读取旧 State，应收敛 `AgentRun.incompatible/runtime_contract_mismatch`，由动态规则决定是否创建新 retry run。
- 业务代码只使用 LangGraph公开 State、graph和 checkpointer契约，不依赖私有表或内部序列化格式。

## 3. 顶层 RunState

顶层 State SHALL 使用显式 typed channels，不使用 `dict[str,Any]`、通用 metadata或全局 working messages：

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

- Graph分别定义公开 input、内部 State和 output schema，避免向 API暴露全部现场。
- 节点把输入视为不可变，只返回自身负责的局部更新；不得原地修改传入 State。
- `AgentRun.status`、cancel权威事实、权限、工具可用性、sandbox策略、审批有效性、异常对象、traceback、大段原始响应和 M06审计事实不得复制进 State。

### 3.1 task_input、phase 与 plan

- `task_input` 是 run创建时的不可变执行快照，至少包含 `input_message_id`、已验证消息内容和 attachment references；业务权威仍是 ConversationMessage。
- `phase` 只服务图内路由，可演进为 planning、selecting_tools、authorizing、awaiting_approval、executing、replanning、synthesizing；它不等于 AgentRun status，只由协调节点覆盖。
- `plan` 至少包含 revision、goal和不可变 plan nodes。State只保存当前 revision，旧 revision由 checkpoint history保留，不另建 plan_history。
- foundation的单节点回答路径可以使用最小 phase/plan值，但必须遵守同一 typed contract，不保留旧 `messages/pending_user/turn_provenance`。

### 3.2 node_outcomes

NodeOutcome 至少可表达 `plan_revision`、`node_id`、`logical_attempt`、outcome、短 observation、retryable、`tool_call_id`、artifact/evidence refs和安全 error code。

- 原始工具输入输出归 M06；State只保存短摘要与稳定引用。
- reducer使用 `(plan_revision,node_id,logical_attempt)` 稳定键：新键加入；同键同内容为幂等重放；同键冲突报一致性错误；最终按稳定键排序。
- 不使用简单追加 reducer，以免 checkpoint replay、并行先后或 worker重试产生重复。只有专门协调/压缩节点可整体替换 channel。

### 3.3 approval_wait

顶层 run同时最多一个 active approval batch；State只保存恢复定位：`approval_id`、plan revision、`node_id/tool_call_id` item refs和 requested time。

- foundation只建立可空 typed边界，不伪造审批 provider或决策；M06/M07 Shape负责首个真实生产者/消费者和字段复核。
- 权威 ApprovalRequest/Items及逐项 decision归 M06。State不保存 `approved=true`；恢复必须重新查询 owner权限、M06、sandbox与有效期。
- 一个 batch后续使用一次 LangGraph interrupt；全部/逐项拒绝形成 NodeOutcome交给 Replanner。参数、工具/策略版本或 operation identity变化使旧 item失效。
- batch决策完成后 run回 queued由任意 worker领取；客户端 resume值不能直接授予权限。

### 3.4 final_answer 与 failure

- `final_answer` 至少包含回答正文和 artifact/evidence refs；`failure` 至少包含稳定 code、安全 message、retryable、failed node ref与可空 source ref。
- 生成/成功节点独占写 final_answer，失败收敛节点独占写 failure；二者互斥，同时存在属于 State不变量破坏。
- State不保存终态 status；finalizer根据公开图状态幂等发布 AgentRun终态与正式消息。

## 4. State 外运行上下文

以下内容通过 LangGraph config、`Runtime[RunContext]`、ActiveRunContext或权威服务取得，不进入 checkpoint：run/conversation/checkpoint identity、ExecutionAuthorization、数据库与模块服务、模型实例、当前权限/工具/sandbox、ProjectionPolicy/manifest、完整历史/工具结果/RAG文档、cancel请求和 AgentRun status。

- `ActiveRunContext` 丢失时可从 AgentRun、checkpoint与 RunGrant重建必要执行环境；无法重建的连接、cancel token和观察者只是性能/传输损失。
- heartbeat失败可在 ActiveRunContext标记 `lease_uncertain`，但不得把该临时标志写成 AgentRun状态。
- 原始发起 session只作审计归因，不成为恢复凭据。

## 5. ContextProjection 管线

每个模型节点 SHALL 在调用前生成一次角色专用 `ModelCallContext`，不得构建贯穿整个 run的一份可变大 Prompt：

```text
LangGraph node
  -> ProjectionInputCollector
  -> typed context providers
  -> ProjectionInput
  -> promptctx pure assembler
  -> ModelCallContext
```

- `promptctx/` SHALL 唯一拥有 ContextBlock、ModelCallContext、BudgetReport、ProjectionPolicy/schema、类型化 ContextSource contract 与确定性 assembler；agent runtime 不得重新定义第二套上下文模型。
- Collector属于 agent application orchestration，无状态、无表、无 checkpoint、无历史缓存；它负责调用顺序、超时、降级和来源版本封装，不写 State、不调用 LLM、不修改权威模块。
- 每次先验证 RunGrant/ExecutionAuthorization，再读 conversation与 State snapshot，然后只调用已真实注册且获授权的 providers。授权失败时不得继续读 memory/tool/evidence。
- 当前只注册 Identity/Conversation/RunState 与已实现 M05 memory 等真实来源；M06--M08 到来时在各自 change 中增加相应强类型 source。未实现能力不注册空 adapter、空文件或占位 block。
- 相同 ProjectionInput与 policy version必须产生相同输出；恢复后重新查询动态权威来源，因此输入本身允许变化。

ProjectionInput metadata至少表达 projection request、run/checkpoint、model role、runtime contract、captured time、source statuses与versions；来源状态使用 `ok|degraded|unavailable|stale`，不宣称跨模块事务快照。

默认来源策略为：身份/RunGrant与 conversation 2秒 fail closed；未来 M06 tool/sandbox/approval 3秒 fail closed；M05 memory 2秒可降级省略；M08 evidence 5秒且 evidence-required节点失败。超时可配置，不能写死在领域逻辑。

## 6. ContextBlock、Prompt 与预算

- 通用上下文类型和预算错误位于 `promptctx/context.py` 与 `promptctx/errors.py`；memory、agent 和 source adapters 只能消费这些公开契约，不得反向拥有 assembler。
- ContextBlock至少表达 block ID、category、source、content、priority、mandatory、token count、source ref、sensitivity与captured time；来源在进入 block前完成授权、过滤和脱敏。
- 裁剪以完整 block/message/observation/evidence为单位，不截断 JSON、工具 schema、消息或引用。
- ModelCallContext结构化区分 system messages、conversation/tool messages、allowed tool schemas、manifest与 BudgetReport；RAG evidence不能伪装成 system指令。
- System Prompt只投影稳定规则、当前角色/节点职责、安全/能力约束和输出契约；任务计划/阶段来自 State，用户请求/历史来自 messages+State，动态权限/工具/sandbox/审批/记忆/evidence在恢复后重新查询。
- Prompt不授予权限、不承担取消/恢复/并发/审计；同一事实只有一个权威来源。

完整输入预算为模型窗口减预留输出、provider overhead与 safety margin，覆盖 system、messages、当前请求、tool schemas、State摘要、memory、evidence与 tool messages。优先用模型 tokenizer，否则保守估算并标记。

- 安全/权限约束、当前请求、节点输出契约、执行必需 State与实际调用工具的完整参数 schema不可裁剪。
- 可选 blocks按稳定策略排序后整块舍弃；必需内容已超限返回结构化 `context_overflow`，不得强行调用模型或在投影器内临时调用 LLM摘要。
- ProjectionManifest/BudgetReport记录 policy version、role、selected/omitted IDs与原因、source versions、token方法/计数和 context digest；默认不永久保存完整 Prompt，不写 State或新事件表。

## 7. ProjectionPolicy 与可修订槽位编排

- ModelRole由当前图节点决定。未知角色、缺失策略或必需 section缺失返回配置错误，不能静默 fallback普通 chat。
- Policy只决定本次需要哪些 section、placement、required、priority、budget、failure policy与强类型 selection；权威 provider决定可读取内容。
- foundation起点只包含真实存在的稳定系统规则、当前安全约束、线性 conversation、task_input、已有安全执行摘要和 output contract。
- M05可增加 profile/recalled memory；M06/M07可增加 plan/outcome、tool capability/observation和 approval约束；M08才增加独立 evidence。没有能力时不占位。
- 区段名、完整角色表、token budget、memory分类和阈值是后续模块 Shape可修订的设计输入。硬边界仅包括：权威来源不迁移到 Prompt、未知角色不降级、来源过滤与全局预算分层、未实现能力不占位。
- 各来源使用自己的强类型 selection，不建立跨来源万能 SlotFilter或通用规则引擎。
- M05 memory 的授权、生命周期、短期/长期/G1 候选与排序位于 `memory/recall.py`；`promptctx/recall_provider.py` 仅执行已合格候选到 ContextBlock 的 source 适配，禁止形成 `memory -> agent` 依赖。

## 8. 图执行、流式与错误

- LangGraph invoke/stream是权威模型执行路径；不得模型直调后用 `update_state`补投影。
- 模型 token可以实时转发给观察 hub，但只有 checkpoint和 finalizer决定恢复/成功；SSE状态不回写 State。
- 节点失败只保存结构化安全摘要、retryability、次数和权威引用；技术 retry有界且可 checkpoint，不捕获异常对象。
- 并行节点各自返回增量，由幂等 reducer确定合并；共享外部副作用必须在 M06引入后使用 operation identity/fencing。

## 9. 验收

- 类型/单元测试证明 State schema、局部更新、幂等 reducer、final/failure互斥、phase/status分离和 runtime contract mismatch。
- checkpoint测试证明每 run隔离、retry不继承、worker恢复同一现场，ActiveRunContext丢失不影响权威恢复。
- Projection测试证明相同输入确定、授权前不访问下游、超时/降级/fail-closed、unknown role、context overflow、完整 block裁剪和预算 manifest。
- 安全测试证明 grant、session、凭据、完整工具/RAG内容和内部 State不进入 API/SSE/Prompt/日志非授权表面。
- 代码复核确认没有通用 event bus、规则引擎、第二套状态、空 provider、`memory -> agent` import 或 checkpointer私表依赖。
