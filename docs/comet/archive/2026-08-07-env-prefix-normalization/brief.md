# Outcome

移除 VenAgent 活动环境变量名称中的 `VENAGENT_` 前缀，并让本地 `.env` 的每一个变量都有紧邻的中文用途说明。

# Scope

- 将 `.env`、`.env.example`、配置加载白名单、测试夹具与配置测试中的 `VENAGENT_` 环境变量统一改为无前缀名称。
- 更新 README 中的活动环境变量说明。
- 保持现有变量的语义、默认值、解析、优先级和秘密脱敏行为。
- 为 `.env` 中每一项变量补充紧邻的中文注释；`.env.example` 维持无真实凭据并同步新名称。

# Non-goals

- 不支持旧 `VENAGENT_` 变量作为兼容别名。
- 不修改历史 Comet 归档、`final/` 旧实现参考或无关的用户工作区改动。
- 不改变 Vue 前端、HTTP API、数据库模式或 LLM provider 行为。

# Acceptance examples

- `SERVER__PORT=8200` 与进程环境中的 `SERVER__PORT=8200` 都映射到 `config.server.port`，后者仍覆盖 `.env`。
- `PERSISTENCE__ENABLED=true`、`AUTH__ALLOWED_ORIGINS_JSON=[...]` 与 `JWT_SECRET=...` 分别保持既有类型解析和秘密处理。
- `.env` 中的 `TEST_DATABASE_URL` 被 pytest 夹具读取；`VENAGENT_TEST_DATABASE_URL` 不再被读取。
- `VENAGENT_SERVER__PORT=8200` 不再配置应用；未知的无前缀结构化键（例如 `SERVER__TYPO=value`）仍快速失败。
- `.env` 的每一个赋值行前都有说明该变量用途的中文注释。

# Constraints and invariants

- 配置优先级保持为安全默认值 < 根 `.env` < 显式进程环境。
- 只接受显式白名单变量；错误消息不得回显秘密、连接串或 `.env` 内容。
- `.env.example` 不得包含真实凭据，`.env` 继续保持 Git 忽略。
- 不改动用户已存在的无关工作区变更。

# Decisions

- 去前缀适用于所有当前活动的 `VENAGENT_` 配置变量：`SERVER__*`、`PERSISTENCE__*`、`AUTH__*`、`JWT_SECRET` 与 `TEST_DATABASE_URL`。
- 不保留旧名称兼容层，避免两个名称产生优先级歧义。
- 模块 intake：M09 platform-governance；采用既有配置加载器（Extend），不新增依赖；仓库检索可用，npm/pip 可用，GitHub CLI 不可用；无需 AGI-saber 对照；当前目录为 `venagent/infra/config`、`tests`、根配置文档，无目录增量；无前端用户操作或状态变更。
- 用户已确认上述完整范围，并批准进入 Build。

# Open questions

无。

# Verification expectations

- 运行定向配置和持久化测试，覆盖 `.env` 与显式环境变量的无前缀加载、优先级、未知结构化键及测试数据库夹具。
- 运行受影响的 Python 测试集与 Comet 文本检查，并记录实际结果。
