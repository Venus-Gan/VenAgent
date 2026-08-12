# Outcome

在本机真实 durable 环境启用用户提供的智谱 `embedding-3` 服务，重启 VenAgent，并完成此前因 embedding 未配置而跳过的供应商级索引与语义召回验收。

# Scope

- 将 embedding endpoint、密钥和模型写入被 Git 忽略的本机 `.env`。
- 停止 8090 上属于本仓库的旧 VenAgent 实例（若存在），启动读取新配置的后台实例。
- 验证配置加载、健康状态、真实批量向量、长期事实索引 job、语义召回和浏览器生命周期。
- 复跑与变更风险相称的 Python、前端和真实数据库检查。

# Non-goals

- 不把真实密钥写入 `.env.example`、Git、Comet brief/spec/report、测试代码或日志。
- 不修改 embedding HTTP adapter、M05 业务契约或默认关闭行为。
- 不更换 PostgreSQL、Neo4j 或 LLM provider。

# Acceptance examples

- 服务重启后的 `/health` 为 durable，PostgreSQL 和 Neo4j 保持 connected/ready，`memory-embedding` 与 `memory-index` 不再是 `embedding_not_configured`。
- 通过现有 `HttpEmbeddingClient` 请求两条无敏感文本，返回两个同维、有限、非零向量；不记录向量或凭据。
- 为隔离测试账号写入稳定事实后，索引 job 完成且真实语义查询召回该事实；不同账号不能召回。
- 真实浏览器记忆生命周期以及项目全量测试继续通过。

# Constraints and invariants

- `.env` 已由 `.gitignore` 排除；所有输出必须脱敏，不展示 endpoint 响应、密钥、向量或用户事实全文。
- 只停止已经验证为本仓库 `.venv` 启动且监听 8090 的进程；不得终止无关进程。
- embedding 失败不得破坏 slot 召回、长期事实持久化或应用启动。
- 真实外部请求只使用合成、无敏感测试文本。

# Decisions

- 用户明确提供 endpoint、密钥和模型，并要求配置、重启及完成剩余测试。
- 使用现有通用 `venagent.llm.embeddings.HttpEmbeddingClient`，不新增 provider 专用 adapter。
- 本轮只做本机秘密配置；长期部署仍应通过 Secret Manager 或环境变量注入。

# Open questions

- 无。

# Verification expectations

- 验证 `.env` 三项配置可被 `load_config()` 启用，但输出仅记录布尔状态和模型名。
- 验证真实 `/embeddings` 返回数量、维度、有限值和非零性。
- 验证重启后的 `/health` 和真实索引/语义召回链路。
- 运行全量 pytest、Ruff、compileall、Vue build 和真实 Playwright M05 用例，并如实记录结果。
