# Outcome

修复 durable PostgreSQL 模式无法完成任何 AgentRun 的缺陷。异步 LangGraph
执行 SHALL 使用支持异步公开契约的 PostgreSQL checkpointer，使真实模型产生的回答能够
完成 checkpoint、发布正式 assistant message，并通过现有 API/SSE 返回给用户。

# Scope

- 修正 PostgreSQL checkpointer 的同步/异步类型选择和连接池生命周期。
- 保持 `AgentRuntime` 的 `aget_state`、`ainvoke` 和异步模型流为权威执行路径。
- 将 checkpoint 删除、应用启动和关闭调整为匹配异步 checkpointer 的公开接口。
- 增加真实 PostgreSQL 下从创建 run 到成功 assistant message 的回归测试。
- 增加 durable runtime 的 checkpoint 写入、读取、删除和资源关闭验证。
- 修复现有测试仅覆盖 `InMemorySaver`、未发现同步 `PostgresSaver` 与异步图不兼容的缺口。

# Non-goals

- 不修改用户取消请求的响应速度、模型请求中断、超时或重试策略。
- 不改变模型 provider、API key、model、base URL 或 Prompt 内容。
- 不引入新的数据库 schema、业务表、旧版本兼容层或 LangGraph 私表依赖。
- 不重构 M05 记忆、M06 工具、M07 规划或 M08 RAG。

# Acceptance examples

- 给定 schema v5 的真实 PostgreSQL 和可控流式模型，当用户创建 run 时，run 在有界时间内
  从 `queued/running` 进入 `succeeded`，数据库保存唯一正式 assistant message，且该
  run 的 LangGraph checkpoint 可由同一 `run_id` 读取。
- 给定 durable runtime，当异步 graph 使用 `aget_state` 与 `ainvoke` 时，不出现
  `BaseCheckpointSaver.aget_tuple` 的 `NotImplementedError`。
- 给定已完成 run，当服务关闭并重新构建 durable runtime 时，可读取同一 checkpoint，
  且不会重复调用模型或重复发布 assistant message。
- 给定删除中的 conversation，当维护任务清理 checkpoint 时，使用异步公开删除接口并在
  成功后删除业务对象；失败时不伪造删除完成。
- 给定 temporary 模式，现有 `InMemorySaver` 对话、SSE、失败和清理行为保持通过。

# Constraints and invariants

- `thread_id=run_id`、per-run checkpoint、AgentRun/State 职责和 finalizer 幂等边界不变。
- 业务仓储继续使用当前同步 PostgreSQL pool；checkpointer 可以拥有独立异步 pool，但两者
  必须由同一应用生命周期显式打开和关闭。
- 普通应用启动不得执行 schema DDL；迁移仍只由 `python -m venagent migrate` 执行。
- 只使用 LangGraph、psycopg 和 psycopg-pool 的公开接口，不读取或写入 checkpointer 私表。
- 启动失败必须关闭已打开资源并沿用现有 durable/temporary 契约，不泄露连接串或凭据。

# Decisions

- 根因已用真实依赖复现：`PostgresSaver` 不实现异步 `aget_tuple`，与当前
  `graph.aget_state/ainvoke` 组合会抛出 `NotImplementedError`。
- 保留异步图和异步模型流，改用官方 `AsyncPostgresSaver`，不把图降为同步执行。
- 业务 PostgreSQL store 与 LangGraph checkpointer 使用职责分离的连接池，避免把 sync/async
  生命周期混合在同一个 adapter 中。
- 本 change 只恢复对话成功路径；取消慢的问题完成本 change 后单独讨论和 Shape。
- 用户已确认按本 brief 范围进入 Build。

# Open questions

无。

# Verification expectations

- 运行真实 PostgreSQL focused tests，禁止因缺少 `VENAGENT_TEST_DATABASE_URL` 跳过核心验收。
- 运行 AgentRuntime、API/SSE、持久化与 checkpoint 恢复相关 pytest。
- 运行全量 pytest、项目级 Ruff、compileall 和前端生产构建。
- 使用真实 FastAPI 服务和浏览器完成一次发送、流式回答、刷新后保留回答的验收；不得只依赖 fake 单测。
- 记录真实模型连通性属于环境证据，不将外部模型稳定性设为自动测试硬门槛。
