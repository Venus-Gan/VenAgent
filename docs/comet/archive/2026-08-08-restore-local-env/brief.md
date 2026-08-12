# Outcome

恢复仓库根 `.env` 的当前配置结构，并尽可能恢复用户已有的本地真实凭据；绝不修改 `.env.example`，也不把凭据写入 Comet 产物或日志。

# Scope

- 依据当前 `.env.example` 与 `refactor-memory-module-layout`、`env-prefix-normalization` 归档契约恢复无前缀环境变量结构和紧邻中文注释。
- 保留当前 `.env` 中已有的 `POSTGRES_PASSWORD` 与 `NEO4J_PASSWORD` 值。
- 将用户本轮提供的 DeepSeek API 配置写回被 Git 忽略的 `.env`；API key 只存在于该文件，不进入任何 Comet 产物。

# Non-goals

- 不修改 `.env.example`。
- 不把占位符当作真实凭据，不生成或猜测用户原有的 JWT secret 或测试连接密码。
- 不修改 Python 配置加载器、Docker Compose、数据库 schema 或应用行为。

# Acceptance examples

- `.env` 包含模板声明的无前缀变量和中文注释，且模板文件内容不变。
- 用户提供的 DeepSeek key 按原值写回，LLM provider 使用当前支持的 `openai_compatible`，API root 为 `https://api.deepseek.com`，思考强度为 `medium`。
- `LLM_MODEL` 使用用户确认的 `deepseek-chat`。
- JWT secret、测试数据库和测试 Neo4j 凭据没有来源时保持缺失，不被占位值替代。
- `.env.example` 的 SHA-256 在 change 前后保持一致。

# Constraints and invariants

- `.env` 保持 Git 忽略；凭据不得进入 README、Comet brief/spec/verification 或命令输出。
- 配置优先级保持为安全默认值 < `.env` < 显式进程环境。
- `PERSISTENCE__*`、`NEO4J__*`、`AUTH__*`、`JWT_SECRET`、`LLM_*` 和测试变量使用 `env-prefix-normalization` 归档后的无前缀契约。

# Decisions

- 用户已明确提供 DeepSeek API key、URL 和中等思考强度，批准写入 `.env`。
- 当前 `.env` 中现存的 PostgreSQL 与 Neo4j 密码继续保留；缺失 JWT 与测试凭据不猜测。

# Open questions

无。

# Verification expectations

- 验证 `.env.example` 未被修改。
- 逐项验证恢复后的 `.env` 变量名称符合 loader 白名单、注释紧邻赋值行，且真实凭据不出现在任何 Comet 产物或 Git diff 中。
