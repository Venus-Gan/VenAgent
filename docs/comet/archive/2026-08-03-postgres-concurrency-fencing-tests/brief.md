# Outcome

补齐 agent-runtime-foundation 遗留的最后一项真实数据库证据：证明 PostgreSQL adapter 在两个独立 worker/连接池并发领取同一个 queued run 时只产生一个有效 claim，并证明 lease 过期接管后旧 worker 的 claim token 与 execution attempt 被 fencing 拒绝。

# Scope

- 重构现有 PostgreSQL 测试装配，让每个真实数据库用例在 `venagent_test` 中获得清洁、隔离的业务数据。
- 新增两个独立 PostgreSQL runtime 并发领取同一个 run 的集成测试。
- 新增 lease 过期、第二 worker 接管、旧 worker 完成失败、新 worker 成功完成的集成测试。
- 运行真实 PostgreSQL 聚焦测试、全量 pytest、项目级 Ruff、compileall 与 Comet 检查。

# Non-goals

- 不修改 PostgreSQL adapter、run 状态机、lease 时长或生产运行行为，除非真实测试发现现有实现不符合已批准契约。
- 不引入 xdist、外部队列、额外数据库容器或常驻测试服务。
- 不测试未来 M05--M08 的记忆、工具、审批或 RAG 行为。
- 不对开发数据库 `venagent` 执行清理、migration 或测试写入。

# Acceptance examples

- 两个独立 PostgreSQL runtime 同时调用 `claim_next` 竞争唯一 queued run，最终恰好一个返回该 run，数据库中的 `execution_attempt` 为 1 且只有一个有效 claim token。
- worker A 领取 run 后 lease 在数据库中到期，worker B 再领取同一个 run，`execution_attempt` 从 1 增为 2 且 claim token 改变。
- 接管后 worker A 使用旧 token/attempt 调用 `succeed` 得到 `InvalidRunTransition`，不能写入回答或终结 run；worker B 使用当前 claim 成功完成且只产生一个 assistant message。
- 配置真实测试连接后，PostgreSQL 聚焦测试和全量 pytest 均 0 skipped，Ruff 与 compileall 通过。

# Constraints and invariants

- 所有破坏性清理只允许作用于 `VENAGENT_TEST_DATABASE_URL` 指向的隔离测试数据库；当前本机目标必须为 `venagent_test`。
- 并发竞争必须使用两个独立的 `PersistenceRuntime`/连接池，不能用 mock、内存 adapter 或单连接顺序调用冒充。
- lease 到期通过测试数据库内的确定性时间更新制造，避免依赖易抖动的长时间 sleep。
- 测试必须关闭所有 runtime/连接池；失败信息不得包含数据库连接串或密码。

# Decisions

- 使用 `owners` 的 `TRUNCATE ... CASCADE` 在每个真实 PostgreSQL 用例前清理隔离业务数据，保留 schema migration 与 LangGraph checkpointer schema。
- 并发领取使用线程屏障同时释放两个 worker；fencing 使用真实数据库将首个 lease 调整为已过期。
- 用户在已明确剩余缺口为真实 PostgreSQL 并发领取、lease 接管与 stale-worker fencing 后要求“如果可以马上就做”，视为对本范围和验收目标的明确确认。

# Open questions

- 无。

# Verification expectations

- 真实 PostgreSQL 聚焦测试必须实际执行且 0 skipped。
- 全量 pytest、`.venv` 内 Ruff、compileall 与 `git diff --check` 通过。
- Comet 文本检查通过，验证报告明确区分真实双连接证据与既有内存领域测试。
- 若测试暴露生产缺陷，Verify 不得通过；应回到 Build 修复并重新封印范围。
