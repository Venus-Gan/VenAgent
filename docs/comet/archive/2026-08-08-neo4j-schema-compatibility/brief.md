# Outcome

恢复当前本地 VenAgent 的 durable 持久化启动：将 PostgreSQL 从现存 v7 schema 前向迁移到当前 v8，同时保持已完成的 Neo4j v1 schema，不再因 PostgreSQL schema 不兼容而降级到进程内存模式。

# Scope

- 使用仓库现有 `python -m venagent migrate` 显式迁移入口处理当前本地 Compose PostgreSQL/Neo4j。
- PostgreSQL v7→v8：保留 owners、conversations、runs、checkpoints、memory facts/sources/jobs 等业务数据；新增 `memory_graph_authority` 与 projection fencing 字段，移除旧 `memory_edges`，建立需要的 Neo4j 冷重建任务。
- Neo4j 已确认 schema version 为 1 且三个 M05 constraints 完整；迁移入口只执行幂等校验/初始化，不重置 Neo4j 数据。
- 迁移后验证 PostgreSQL schema version、必需表、旧表移除、应用 durable 状态和 Neo4j 图能力状态。

# Non-goals

- 不修改 PostgreSQL/Neo4j 密码、连接配置、Compose volume 或现有业务数据内容。
- 不改变正常应用启动只校验 schema、不静默执行 DDL 的既有契约。
- 不新增自动迁移、兼容旧 schema 的运行时回退、双写或 PostgreSQL 图边存储。
- 不修改产品功能、HTTP/命令行为、前端或 legacy `final/`。

# Acceptance examples

- 给定当前 PostgreSQL migration history 为 `[7]`，执行显式迁移后 history 为 `[8]`，`memory_graph_authority` 存在且 `memory_edges` 不存在。
- 给定现有 PostgreSQL v7 业务数据，迁移不会删除 owners、conversations、runs、checkpoints、memory facts/sources/jobs。
- 给定 Neo4j schema version 1 与完整 M05 constraints，迁移保持兼容且不清空图数据。
- 给定两个容器健康且配置有效，迁移后启动应用时 PostgreSQL 状态为 durable/connected，不再记录 `persistence_schema_incompatible`；长期记忆与 GraphMemory 不再因 `durable_identity_required` 被禁用。

# Constraints and invariants

- 只对仓库 `.env` 当前指向的本地 Compose 数据库执行；不得输出连接串、密码或原始驱动异常中的秘密。
- 迁移前已只读确认 PostgreSQL 为 v7、缺少 `memory_graph_authority` 且仍有 `memory_edges`；不得按“无迁移历史”的重建路径处理。
- PostgreSQL 与 Neo4j 分别提交、分别验证，不声称跨库原子性。
- 使用现有迁移实现，不通过手工 SQL 绕过 migration history、advisory lock 或幂等逻辑。
- 既有工作树改动由用户所有；本 change 不重写或回退无关文件。

# Decisions

- Adopt 现有显式 migration CLI；本次问题是本地 PostgreSQL 仍停留在 v7，而不是 Neo4j schema 版本错误。
- 保留全部 v7 权威业务数据，旧 PostgreSQL 图边不迁移；Neo4j 图投影按 PostgreSQL 权威 facts/sources 冷重建。
- Neo4j 当前 v1 schema 视为兼容，不重置 volume 或节点。
- 用户已于 2026-08-08 确认执行当前本地 PostgreSQL v7→v8 前向迁移与 Neo4j v1 幂等迁移，并要求出现问题时及时修复。

# Open questions

无。

# Verification expectations

- 记录迁移命令真实结果，不回显秘密。
- 只读查询确认 PostgreSQL version `[8]`、必需表完整、`memory_edges` 已移除，并抽样核对关键业务表行数在迁移前后未减少。
- 运行应用装配/生命周期检查，确认持久化状态为 durable 且 Neo4j GraphMemory 进入 healthy。
- 运行迁移与持久化相关 pytest、Neo4j 相关 pytest，以及与变更风险匹配的静态/编译检查；不可用或跳过项如实记录。
