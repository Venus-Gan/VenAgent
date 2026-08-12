# Outcome

保留 `.env` 与部署环境现有的 LLM/数据库秘密变量名，同时继续使用 YAML 管理非敏感结构化配置。

# Scope

- 允许 `LLM_*` 与 `VENAGENT_DATABASE_URL` 作为秘密和 LLM 覆盖输入。
- 更新加载器、模板、文档与测试。

# Non-goals

- 不把非敏感 LLM 默认值重新堆回 `.env`。
- 不输出或改写本机秘密值。

# Acceptance examples

- 现有 `.env` 中的 `LLM_API_KEY` 与 `VENAGENT_DATABASE_URL` 可正常启动应用。
- `config.local.yaml` 继续保存 provider、model、URL 等非敏感设置。

# Constraints and invariants

- 显式进程环境仍覆盖 `.env`；YAML 不允许秘密。

# Decisions

- 用户明确要求外部环境键与 `.env` 保持 `LLM_*` / `VENAGENT_DATABASE_URL` 一致。

# Open questions

- 已确认：仅恢复环境变量命名兼容，不放弃 YAML 配置边界。

# Verification expectations

- 运行配置、LLM 与 API/持久化回归测试。
