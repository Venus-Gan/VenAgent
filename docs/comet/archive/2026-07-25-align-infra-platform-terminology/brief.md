# Outcome

使当前文档、架构规格与实际 `venagent/infra/platform/` 包目录一致，避免后续模块按已废弃的 `infra/persistence/` 路径开发。

# Scope

- 将 README 的运行时目录树从 `persistence/` 更正为 `platform/`。
- 将 feature-first package layout 的完整目标规格固定为 `infra/platform/` 与 platform runtime。
- 保持“conversation persistence”作为对话持久化能力、健康检查字段、错误码、测试名与运行时类型的术语。

# Non-goals

- 不移动或重命名当前 `venagent/infra/platform/` 的 Python 文件。
- 不更改 HTTP/SSE 契约、健康检查字段、错误码、日志名称、测试模块名称或数据库 schema。
- 不改写已归档的 Comet 产物或 runtime transaction 历史。

# Acceptance examples

- README 的目录树将当前 adapter 目录显示为 `infra/platform/`。
- canonical `feature-first-package-layout` 规格要求 `infra/platform/` 承担内存和 PostgreSQL adapter、迁移与启动 runtime selection。
- `conversation_persistence`、`PersistenceRuntime` 和 `persistence_unavailable` 等现有业务术语保持不变。

# Constraints and invariants

- `platform` 仅是当前 infra 子包的目录/架构名称；它不替代对话持久化能力的对外术语。
- 只修改可演进的 canonical 文档与 README；归档和 Runtime 管理产物保持不可变。
- 不触及用户工作区中与此文档修正无关的未提交重构改动。

# Decisions

- 用户确认执行此前列出的目录术语修正：将 `infra/persistence` 文档路径改为 `infra/platform`，保留 persistence 领域术语。
- 当前 canonical feature-first 规格已由用户手动更正为 `infra/platform/`；本 change 将其作为完整 replace 规格封存，README 同步该事实。

# Open questions

- 已确认：不将 logger `venagent.persistence`、公共健康字段、错误码、类型名或测试名重命名为 platform。

# Verification expectations

- 检查 README 与 canonical feature-first 规格不再包含 `infra/persistence` 路径。
- 运行相关 package-layout 测试，确认文档修正不改变现有路径约束。
