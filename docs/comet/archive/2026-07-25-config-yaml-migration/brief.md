# Outcome

将当前运行时从以 `.env` / 平铺环境变量为中心的配置方式迁移为结构化 YAML 配置，同时保留安全的部署覆盖和未配置 LLM 时的离线本地模型行为。

# Scope

- 在当前 `venagent/` 运行时建立受校验的 YAML 配置模型、默认共享配置与本地覆盖配置。
- 让 LLM 与 PostgreSQL 装配从统一配置对象读取，而不是分别直接读取 `.env` 和 `os.environ`。
- 更新 `.env.example`、Compose、README 和测试，以说明配置来源、优先级、密钥边界及部署覆盖方式。
- 维持现有 HTTP/SSE、数据库 schema、持久化降级语义和 provider adapter 行为。

# Non-goals

- 不直接复用或恢复已删除的 `src/venagent/infrastructure/config/` 包。
- 不把 API key、数据库密码或连接串提交到仓库。
- 不实现 RAG、MCP、认证或其他后续模块的配置项。

# Acceptance examples

- 用户可通过仓库跟踪的 `config/config.yaml` 设置非敏感 LLM、服务器与持久化默认值。
- 用户可用本地覆盖和部署环境变量改变支持的字段；未知字段、类型错误和无效组合会在启动前安全失败。
- 未配置真实 LLM 时，应用仍选择无网络的本地回复模型；配置真实 LLM 时仍执行当前 provider 完整性校验。
- 任何配置或错误输出均不显示 API key、密码或完整数据库连接串。

# Constraints and invariants

- 合并顺序必须稳定、文档化且可测试；显式进程环境变量优先于本机文件与共享默认值。
- 配置文件路径、字段和覆盖键必须有白名单与类型校验，不能将任意环境变量透传给应用。
- 现有未提交工作区修改视为基线；本 change 只记录自身的增量，不重置或改写无关变更。

# Decisions

- 用户要求避免将项目配置全部堆入 `.env`，并以旧项目的 YAML 结构为参考，而非直接迁移其实现。
- 用户确认不以当前未提交工作区状态阻塞本 change。
- 敏感值仅允许通过部署环境或 Secret Manager 注入；`config/config.yaml` 与 `config/config.local.yaml` 均不得包含 API key、密码或完整数据库连接串。
- 用户选择直接切换至 `VENAGENT_<SECTION>__<FIELD>` 覆盖键，不保留 `LLM_*` 或 `VENAGENT_DATABASE_URL` 的兼容期。
- 用户确认以上完整配置契约，并要求对非直观的配置加载、覆盖和安全边界添加中文注释。

# Open questions

- 已确认：在不改动 HTTP/SSE、对话持久化降级或 provider 行为的前提下，新增严格 YAML 配置层；其优先级为内建默认值 < `config/config.yaml` < 被忽略的 `config/config.local.yaml` < `.env` < 显式进程环境变量。YAML 不接受秘密；新覆盖键采用 `VENAGENT_LLM__*`、`VENAGENT_SERVER__*` 与 `VENAGENT_PERSISTENCE__DATABASE_URL`，旧 `LLM_*` 和 `VENAGENT_DATABASE_URL` 在启动时以明确迁移错误拒绝。

# Verification expectations

- 覆盖 YAML 层级、环境覆盖、类型/未知字段校验、密钥脱敏、离线模型回退与旧部署变量的选定行为。
- 验证 CLI、FastAPI 装配、相关 Python 回归测试及配置文档示例。
