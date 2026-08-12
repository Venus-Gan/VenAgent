# Outcome

VenAgent 的显式取消应在请求被持久接受后立即向用户显示“正在停止”，并由拥有当前 claim 的 runtime 主动中断可取消的 LangGraph/模型等待；健康运行不得依赖模型下一个 token 或 60 秒 lease 过期才收敛。取消与成功 finalizer 并发时必须保持消息、checkpoint 与 AgentRun 终态不变量。

# Scope

- 修复当前进程内 cancel token 只能轮询、不能唤醒正在等待模型 chunk 的问题。
- 增加独立于 15 秒 lease heartbeat 的持久取消观察，使另一进程接受的取消在有界观察周期内被当前 worker 发现。
- 修复最后一个 token、最终 checkpoint 与成功 finalizer 之间的取消竞态，避免 run 保持 `running + cancel_requested_at` 等待 lease 接管。
- 让取消终态写入匹配当前 claim/fencing，旧 worker 不得发布迟到终态。
- 前端消费 `cancel_requested_at`，在取消 API 返回 202 后立即显示“正在停止”、禁止重复取消并丢弃该 run 的迟到 token，直至权威终态到达。
- 增加阻塞首 token、chunk 间等待、最后 token/finalizer 竞态、跨 runtime 通知和前端协议回归测试，并进行真实后端、真实模型与真实浏览器验收。

# Non-goals

- 不增加 `cancelling` AgentRun 状态，不改变既有终态集合。
- 不实现 M06 工具、副作用回滚、审批取消或完整 cancellation reconciler；外部操作接入后仍须先对账真实事实。
- 不引入消息队列、通用事件总线、PostgreSQL LISTEN/NOTIFY 或 LangSmith Agent Server。
- 不把取消请求写入 LangGraph State/checkpoint，也不删除取消 run 的 checkpoint。
- 不修改 60 秒 lease 与 15 秒 heartbeat 已批准基线。

# Acceptance examples

- 模型在首 token 前长时间等待时，用户取消后 graph/model task 被主动取消，run 快速进入 `cancelled`，不创建 assistant message，也不等待模型自然产出 token。
- 取消发生在最后一个 token 已消费、模型流尚未结束或 finalizer 提交前时，取消请求先持久成功则不得发布回答，run 不得滞留 `running` 等待 lease 过期。
- 取消由非执行 worker 的进程接受时，执行 worker 在最多一个专用取消观察周期后发现请求；该路径不依赖 15 秒 heartbeat。
- 取消 API 返回 202 后，页面立即显示“正在停止”并禁止再次点击；权威 `cancelled` 到达后显示“已取消”并恢复输入。
- 取消请求前 finalizer 已提交成功时，后续取消返回既有 `succeeded`，不改写正式 assistant message。
- SSE 断线、页面刷新或关闭仍不触发隐式取消。

# Constraints and invariants

- `AgentRun.cancel_requested_at` 是取消请求权威事实；进程内信号只加速当前 worker。
- `AgentRun.status` 仍固定为 `queued|running|waiting_approval|succeeded|failed|cancelled|incompatible`。
- 只有当前 `run_id + claimed_by + claim_token + execution_attempt` 可以完成 running run 的取消收敛。
- LangGraph task 取消只保留最后完成的公开 checkpoint；不得用 checkpointer 私表实现控制面。
- assistant message 与 `succeeded` 必须原子发布；`cancelled` run 不得拥有 output message。
- 传输层和前端不能自行写业务终态；UI 的“正在停止”只是已接受取消请求的投影。
- Python 并发、claim/fencing 和取消竞态实现处添加简洁的原因注释。

# Decisions

- 采用“持久请求 + 进程内主动 task cancellation + 专用持久取消观察”的双路径。
- 专用取消观察与 lease heartbeat 分离，初始周期取 0.5 秒；未来只有真实吞吐证据才升级消息通知机制。
- 保留无 `cancelling` 状态的既有生命周期，通过 `cancel_requested_at` 派生前端“正在停止”。
- 当前纯模型节点在 graph task 确认停止后即可收敛 cancelled；未来 M06 外部操作必须先对账真实副作用。
- 用户已在本轮分析结论后明确批准上述方案。

# Open questions

无。

# Verification expectations

- 运行取消、streaming、commit recovery、PostgreSQL 持久化和 HTTP/SSE 相关 pytest；随后运行全套后端测试。
- 使用真实 PostgreSQL 覆盖跨 runtime 持久取消观察和 fencing，若环境不可用必须如实记录。
- 运行项目级 Ruff、compileall、前端 TypeScript 检查与生产构建。
- 启动真实 FastAPI 与前端，通过真实模型在浏览器执行发送、停止中反馈、取消终态、刷新恢复和后续再次发送；检查网络请求、控制台错误、迟到 token 和永久 busy。
- 执行 Comet 文本检查并记录所有跳过项、耗时证据与剩余 M06 风险。
