# README 目录结构

## 目标

README 必须以当前仓库的 feature-first 渐进式运行时为准，提供可用于定位模块职责的文件树。

## 行为

- “目录结构”中的运行时树必须列出 `venagent/` 的 agent、conversation、ownership、memory 业务能力，独立 `promptctx/`，`repo/` adapters，`platform/` 技术资源与 security，`llm/`、`config/`、HTTP 接口层、composition root 和 CLI；不得再列出活动 `infra/`。
- 运行时树中列出的每个目录和文件必须使用同行简短注释说明职责或所有权；注释应能区分相邻文件，例如明确 `ownership.py` 收回 ownership 映射、`conversation_mapping.py` 共享 conversation/message/run 映射，而不是只标记“模块”或重复文件名。
- 树必须单独列出根 `web/`，并说明它是 Vue 3 前端；其生产构建由 FastAPI 托管。
- `agent/` 的职责描述只列出当前 M01--M05 文件；不得预建或描述 M06--M09 的 planner、tool、RAG、queue 等活动目录。
- 树后说明必须明确 `repo` 与 `platform` 分类、`bootstrap.py` 唯一 adapter 装配、PostgreSQL/Neo4j 资源所有权、promptctx 与 memory/agent 的依赖方向，以及 HTTP 层不取得原始数据库连接的边界。
- `final/` 必须继续标记为旧项目实现与功能参考，不是当前运行时包边界。

## 非目标

- 本能力不改变项目代码、目录布局、配置加载或运行时行为。
