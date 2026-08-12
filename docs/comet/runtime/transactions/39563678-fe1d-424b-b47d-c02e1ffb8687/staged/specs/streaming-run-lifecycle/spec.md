# Streaming Run Lifecycle 完整目标规格

## 1. 目标

VenAgent SHALL 将 Agent 执行建模为可持久查询、可恢复和可取消的 `AgentRun`。HTTP/SSE 连接只观察运行，不创建隐式生命周期，也不因断开、刷新或浏览器退出自动取消 run。

## 2. AgentRun 状态与字段

- 持久 run 至少包含 `run_id`、`conversation_id`、`owner_id`、`input_message_id`、可空 `output_message_id`、`grant_id`、`retry_of_run_id`、`status`、`runtime_contract_version`、创建/更新/开始/完成时间、取消请求、终态 reason/message、claim/lease/fencing 字段和安全进度摘要。
- status 固定为 `queued|running|waiting_approval|succeeded|failed|cancelled|incompatible`；后四者为终态，不增加 `cancelling` 状态。
- 终态 reason 使用稳定 code，安全 message 不得包含异常栈、凭据、Prompt、工具参数或原始响应。`retry_eligible` 与拒绝原因在查询时按最新事实计算，不持久化为权威字段。
- 数据库 SHALL 保证每个 conversation 同时最多一个 `queued|running|waiting_approval` run。

## 3. 生命周期所有权

- `AgentRunLifecycle` 是 status 唯一业务写入口；所有转换通过状态机、数据库 CAS 与当前 fencing token 校验。
- Conversation command 只能创建 queued；scheduler claim 执行 `queued->running` 或过期 running 接管；checkpoint reconciler 可投影 waiting；approval resume service 可 `waiting_approval->queued`；finalizer/reconciler 负责终态。
- HTTP route、LangGraph node、SSE adapter、scheduler 和 store adapter 不得直接越权写终态。scheduler 不能把模型或工具错误直接标成 failed。
- 每次状态变化更新 `updated_at`；终态写完成时间、reason 并释放 claim。当前不新增通用运行事件表。

## 4. 创建、claim 与恢复

- 创建 run 与 user message、RunGrant、单活跃占用处于同一事务；成功返回 HTTP 202，事务提交前不得提交给执行器。
- queued run 本身是待领取集合。默认按 `created_at,run_id` FIFO 原子领取，不建设独立消息队列或优先级系统。
- 默认参数为 lease 60 秒、heartbeat 15 秒、claim poll 2 秒加 jitter、cancel observation 0.5 秒、单 worker 顶层并发 2、单 owner running 上限 2、连续无 checkpoint 进展恢复上限 3；配置不得散落或写死在领域逻辑。
- 时间判断使用数据库时间。claim 原子更新 `claimed_by`、新 `claim_token`、`lease_expires_at` 和递增 `execution_attempt`；heartbeat、状态更新、取消收敛和 finalizer 必须匹配当前 fencing 组合。
- heartbeat 独立于 LangGraph 节点结束；高风险外部动作前 lease 不足时必须先续租。waiting 和终态立即释放 worker lease，但 waiting 继续占用 conversation 单活跃权。
- 数据库或 claim 能力不确定时停止新领取、新模型调用和新副作用。旧 worker 不得提交迟到写；恢复后由当前 claim 对账。
- worker 失联但 checkpoint 有进展时恢复同一 run；连续三次无进展才收敛 `failed/infrastructure_unrecoverable`。`execution_attempt` 不等于用户 retry。

## 5. 取消与竞态

- 取消先持久写入 `cancel_requested_at` 与请求来源；进程内 token 仅加速通知，不是权威事实。
- `ActiveRunContext` SHALL 为当前事件循环保存可等待取消信号和正在执行的 graph/model task。当前进程收到取消通知时必须线程安全地唤醒拥有 task 的事件循环，并主动取消仍在等待的 LangGraph/模型协程，不能只在模型下一个 token 后轮询。
- 当前 worker SHALL 使用独立于 lease heartbeat 的持久取消观察。另一进程写入的取消在最多一个健康观察周期后被发现；观察读取失败按 lease 不确定边界处理，不伪造 cancelled。
- graph/model task 确认停止后，取消 reconciler 使用当前 claim/fencing 收敛 `cancelled` 并发布权威观察；旧 claim 的迟到取消写必须被拒绝。
- 图在节点边界、恢复点和外部副作用前再次检查持久取消。已发出的外部操作不得伪装回滚；M06 后续必须先对账真实操作再允许 run 收敛 cancelled。
- waiting run 被取消时关闭/失效其审批等待。owner/conversation 删除或安全撤销使用对应稳定 reason。
- finalizer 事务先成功时取消返回既有 succeeded；取消请求先 CAS 成功时 finalizer 不发布 assistant message，并立即进入取消对账，不得吞掉转换冲突后等待 lease 过期。禁止 succeeded 无 output message，也禁止 cancelled 已发布 assistant message。
- provider 不响应协程取消或外部副作用仍在执行时不得用 UI 请求确认伪造业务终态；由当前执行层保持 fencing 并继续安全对账。

## 6. Checkpoint 与 finalizer

- 每个 run 使用独立 LangGraph checkpoint 链，adapter 唯一映射 `thread_id=run_id`；conversation 之间及 retry 之间不得共享或继承 checkpoint。
- 图暂停或完成时先确保 checkpoint 成功，再投影 AgentRun。对账只使用 LangGraph 公开状态/checkpointer API。
- 取消正在执行的 graph task 时保留最后完成的公开 checkpoint，不删除 checkpoint、不写伪造完成状态，也不查询 checkpointer 私有表。
- 成功顺序固定为：最终 checkpoint；确认无 active interrupt 且存在合法 `final_answer`；在一个业务事务插入 assistant message、设置 output ID、更新 succeeded/conversation 并释放 claim；事务提交后才发送 completed。
- finalizer 可幂等重放。最终 checkpoint 后、业务事务前崩溃时重新 finalizer；业务事务后、通知前崩溃时查询既有结果；数据库暂不可用时保持非终态等待恢复。
- checkpoint 中 `final_answer` 与 `failure` 必须互斥；active interrupt 投影 waiting，有下一节点保持 running，contract 不匹配投影 incompatible，持续无法安全发布才在对账后使用 `failed/finalization_failed`。

## 7. HTTP 与 SSE

目标协议至少包含：

```text
POST /api/conversations/{conversation_id}/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/stream
POST /api/runs/{run_id}/cancel
POST /api/runs/{run_id}/retry
POST /api/approvals/{approval_id}/decision
```

- 创建接口使用 conversation 范围内唯一 `client_request_id`，返回 202、run ID、input message ID 和 status；重复同义请求返回既有结果，冲突语义返回 409。
- cancel 接口在权威请求持久化后返回 202；它只确认请求已接受，不宣称 graph 已停止或 run 已终态。
- run 查询返回身份关联、status、取消请求、终态原因、安全 message、动态 retry 投影、安全进度/审批摘要和主要时间戳；不得返回完整 State、checkpoint、Prompt 或秘密。
- SSE 新连接首个业务事件始终为当前权威 `snapshot`，后续 MAY 发送 `status|progress|token|approval_required|completed|failed|cancelled|incompatible`。取消请求被接受后 SHOULD 及时发送包含 `cancel_requested_at` 的权威 snapshot/status 投影。
- token 只代表该连接建立后观察到的实时增量；不持久化 token delta、不承诺 `Last-Event-ID` 重放。terminal run 发送 snapshot 与相应终态后关闭。
- 同一 owner 可以有多个观察连接；连接数量、断开和重连不改变 run。SSE 不可用时前端轮询同一 run projection。
- 所有 query/stream/cancel/retry/approval 操作按 owner 授权；不存在与跨 owner 访问使用同一 404 风格安全错误。

## 8. 前端收敛

- 前端收到创建响应后才建立 run 观察。snapshot 是页面加载、重连和轮询回退的权威起点。
- `cancel_requested_at` SHALL 投影为非终态的“正在停止”，而不是新的 AgentRun status。cancel API 返回 202 后客户端立即采用已接受请求的本地投影，禁用重复取消；后续 snapshot 覆盖该投影。
- token 只追加到以 run ID 为键的进程内 partial；不得写 localStorage、正式消息或恢复事实。run 已投影取消请求后，客户端丢弃该 run 的迟到 token。
- completed 后读取/采用服务端正式 assistant message 并完整替换 partial；failed/cancelled/incompatible 清理或保留仅本次页面可见的 partial 提示，但不上传。
- 迟到事件、旧 run、conversation/owner 不匹配事件必须丢弃。终态后取消、审批和输入状态立即禁用/收敛。
- 用户显式 retry 返回新 run ID，旧 run 保持原终态；网络不确定时不得无条件新建 retry，而应先按 client request ID/query 对账。

## 9. 验收

- 覆盖状态转换、非法转换、单活跃、claim/fencing、lease 接管、heartbeat 失败、无进展预算和数据库不可用 fail closed。
- 故障注入覆盖首 token 阻塞时取消、chunk 间取消、最后 token/模型结束/finalizer 窗口、跨 runtime 持久取消观察、重复取消、旧 claim 迟到取消、checkpoint 后未发布、发布后未通知、重复 finalizer 和 contract mismatch。
- HTTP/SSE 测试证明 202 只确认请求、snapshot 首发、取消请求投影、实时 token、取消后迟到 token 丢弃、无 replay、多个观察者、轮询回退、断连不取消、跨 owner 不泄露和终态收敛。
- PostgreSQL 验证证明跨 runtime 取消不依赖 15 秒 heartbeat，取消/成功 CAS 与 fencing 在实库成立。
- 真实浏览器使用真实模型证明取消请求后立即显示“正在停止”、随后权威 cancelled、输入恢复且可继续发送；同时证明刷新/关闭后后台继续、没有永久 busy、重复回答、迟到 token 或跨对话 token。
