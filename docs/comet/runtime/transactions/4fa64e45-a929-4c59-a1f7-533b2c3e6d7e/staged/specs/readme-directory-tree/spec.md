# README 目录结构

## 目标

README 必须以当前仓库的 feature-first 渐进式运行时为准，提供可用于定位模块职责的文件树。

## 行为

- “目录结构”中的运行时树必须列出 `venagent/` 的业务能力目录、`infra/` 的配置、安全、LLM、memory 与 platform 子目录、HTTP 接口层、composition root、CLI 与可观测性模块。
- 树必须单独列出根 `web/`，并说明它是 Vue 3 前端；其生产构建由 FastAPI 托管。
- `agent/` 的职责描述不得包含不存在的 `worker` 文件或目录。
- 树后说明必须保留 adapter 分类、连接资源所有权和 HTTP 层不取得原始数据库连接的架构边界。
- `final/` 必须继续标记为旧项目实现与功能参考，不是当前运行时包边界。

## 非目标

- 本能力不改变项目代码、目录布局、配置加载或运行时行为。
