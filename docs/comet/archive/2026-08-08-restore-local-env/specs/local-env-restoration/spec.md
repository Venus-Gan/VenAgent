# 本地环境配置恢复

## 目标

恢复根 `.env` 的活动配置，使本地应用可以使用用户提供的 DeepSeek 配置，同时保持模板和凭据边界不变。

## 行为

- `.env` 使用 `env-prefix-normalization` 归档后的无前缀变量名称，并为每个赋值行保留紧邻的中文用途注释。
- `LLM_PROVIDER` 设置为 `openai_compatible`，因为当前代码通过 OpenAI-compatible adapter 接入 DeepSeek。
- `LLM_BASE_URL` 设置为 `https://api.deepseek.com`；`LLM_ENDPOINT_URL` 保持为空，避免同时配置 API root 与完整 endpoint。
- `LLM_MODEL` 设置为用户确认的 `deepseek-chat`。
- `LLM_REASONING_EFFORT` 设置为 `medium`。
- 用户提供的 `LLM_API_KEY` 只写入被 Git 忽略的 `.env`，不得写入 `.env.example`、README、Comet brief/spec/verification、日志或测试产物。
- 当前 `.env` 中已有的 PostgreSQL 与 Neo4j 密码保持不变；没有来源的 JWT、测试数据库和测试 Neo4j 凭据保持缺失。

## 非目标

- 不修改 `.env.example`。
- 不修改配置加载器、Docker Compose、数据库 schema、LLM adapter 或运行时行为。
