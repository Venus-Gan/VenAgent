# Outcome

PostgreSQL 的非敏感基础设施配置随应用包保存在 `venagent/config/`，应用仅从环境读取数据库密码，并可在启动时直接使用已迁移的 PostgreSQL 服务。

# Scope

- 将共享 YAML 和本地 YAML 覆盖从仓库根 `config/` 迁至 `venagent/config/`。
- 在 YAML 中定义 PostgreSQL 是否启用、主机、端口、数据库名和用户名。
- 从 `POSTGRES_PASSWORD` 注入密码并由配置对象安全组装连接串。
- 将 Vite 开发代理与默认 `server.port` 对齐，避免前端开发服务指向过期端口。
- 更新 Compose、模板、文档、包数据与测试。

# Non-goals

- 不将 LLM API key、数据库密码或完整数据库连接串写入 YAML。
- 不自动执行数据库迁移或修改用户现有数据库数据。

# Acceptance examples

- 默认 YAML 启用本机 `127.0.0.1:5432` 的 `venagent` PostgreSQL 服务；提供 `POSTGRES_PASSWORD` 后，应用配置可生成连接串而不回显密码。
- 未提供 `POSTGRES_PASSWORD` 时，应用保持受支持的内存降级模式，并说明 PostgreSQL 未配置。
- 包安装后仍能读取随 `venagent` 分发的默认 YAML；`venagent/config/config.local.yaml` 保持为被忽略的本机非敏感覆盖。
- 默认后端端口为 `8090` 时，Vite 对 `/api` 与 `/health` 的开发代理也转发到 `127.0.0.1:8090`。

# Constraints and invariants

- 显式进程环境覆盖 `.env`；YAML 仍拒绝所有秘密字段。
- PostgreSQL URL 组装必须对用户名、密码和数据库名正确进行 URL 编码，且错误与日志不得回显秘密。
- 既有 `LLM_*` 行为不变。

# Decisions

- 用户确认 PostgreSQL 的启用状态、主机、端口、库名和用户名写入 YAML。
- 用户确认数据库密码仅保留为 `POSTGRES_PASSWORD` 环境变量。
- 用户确认配置目录迁入 `venagent/config/`，并要求中文注释。
- 用户确认 Vite 开发代理与当前默认后端端口 `8090` 对齐。

# Open questions

- 已确认：不接受完整数据库连接串作为常规配置输入。

# Verification expectations

- 覆盖 YAML 层级、密码注入、无密码降级、连接串编码和包内默认配置定位。
- 运行配置、持久化与启动相关测试；数据库迁移仅在用户明确要求时执行。
