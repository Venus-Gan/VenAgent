# 异步 PostgreSQL Checkpoint Runtime 完整目标规格

## 1. 目标

VenAgent durable 模式 SHALL 为异步 LangGraph 图提供兼容的 PostgreSQL checkpointer。
`AgentRuntime` 使用 `aget_state`、`ainvoke` 或其他异步图公开接口时，checkpointer SHALL
实现对应的异步读取、写入、列举和删除契约，不得把只支持同步调用的 saver 传给异步图。

## 2. 生命周期与所有权

- durable runtime SHALL 使用官方 `AsyncPostgresSaver` 或具有等价公开异步契约的 adapter。
- checkpointer 的异步连接池 SHALL 由 `PersistenceRuntime` 拥有，并在 FastAPI lifespan
  进入服务态前打开，在 worker 和维护任务停止后关闭。
- 业务 conversation、ownership 与 AgentRun store MAY 继续使用独立同步连接池；两个连接池
  不共享未明确支持的连接对象，也不互相承担事务。
- temporary runtime SHALL 继续使用 `InMemorySaver`，并提供与应用生命周期兼容的无操作打开/关闭行为。
- 任一初始化步骤失败时 SHALL 关闭此前已打开的资源，不启动 Agent worker，不暴露数据库秘密。

## 3. 图执行与恢复

- 每个 `AgentRun` 继续使用 `thread_id=run_id` 的独立 checkpoint 链。
- 新 run 的异步图执行 SHALL 写入 checkpoint；完成后 AgentRun finalizer SHALL 原子发布唯一
  assistant message 和 `succeeded` 终态。
- worker 接管已有 run 时 SHALL 能通过异步公开接口读取 checkpoint。已存在 `final_answer`
  时只重放幂等 finalizer，不重新调用模型。
- checkpoint 故障不得伪造成功、失败或取消。已有 claim/lease/fencing 和数据库不确定性规则保持不变。
- conversation/owner 删除 SHALL 通过异步公开删除接口清理 run checkpoint；清理失败时业务对象留待重试。

## 4. Schema 与迁移

- 应用启动 SHALL 只验证 VenAgent schema v5 和官方 checkpointer schema，不执行 DDL。
- `python -m venagent migrate` 继续使用官方同步迁移入口执行一次性 `setup()`；运行时异步
  checkpointer SHALL 复用同一官方 schema。
- VenAgent 不查询、扩展或绑定 LangGraph checkpointer 私有物理表。

## 5. 错误与可观测性

- sync/async saver 契约不匹配 SHALL 在自动测试中失败，不得以长时间 `running` 或空白回答表现。
- checkpointer 初始化或调用错误 SHALL 进入现有安全错误边界，不记录连接串、密码、checkpoint blob 或完整 Prompt。
- 本规格不定义模型调用取消、请求超时和重试；这些行为由后续独立 change 处理。

## 6. 验收

- 真实 PostgreSQL 测试证明异步 `aget_state/ainvoke` 可读写 checkpoint，不抛出
  `NotImplementedError`。
- 真实 PostgreSQL API 测试证明 run 成功、唯一 assistant message、SSE 终态与刷新恢复。
- 重建 runtime 后能够读取同一 run checkpoint，并且 finalizer 重放不会重复调用模型或写消息。
- checkpoint 删除和应用关闭释放异步及同步连接池；失败路径不遗留假终态。
- temporary 模式和既有全量测试保持通过。
