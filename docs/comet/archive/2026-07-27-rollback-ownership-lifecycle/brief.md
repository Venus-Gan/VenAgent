# Outcome

移除已归档 M04 的用户、所有权与账号界面实现，恢复 M03 的匿名对话行为；保留已归档 PostgreSQL 配置 change 和 Vite 到 `8090` 的开发代理。

# Scope

- 按 `ownership-lifecycle` 归档的完整实现范围，移除用户、访客所有者、账号 Cookie、认领、删号、所有权校验和账号界面。
- 恢复 M03 的 conversation、HTTP、持久化迁移与前端聊天行为。
- 移除 M04 的账户测试、端到端测试与浏览器导入/认领相关用户表面。
- 保留 `venagent/config/`、PostgreSQL YAML 配置、`POSTGRES_PASSWORD` 注入及 `web/vite.config.ts` 对 `8090` 的代理。

# Non-goals

- 不改写 `docs/comet/archive/2026-07-26-ownership-lifecycle` 的历史归档记录。
- 不新增替代性的账户、登录、用户历史、认领或导入功能。
- 不改变 Docker PostgreSQL 容器的运行状态。

# Acceptance examples

- 应用不再暴露账号注册、登录、登出、认领或删号 API，也不再渲染账户侧栏与账号弹窗。
- 匿名用户仍可创建、聊天、导入和删除 M03 对话；Vite 仍将 `/api` 与 `/health` 代理到 `127.0.0.1:8090`。
- PostgreSQL 在回退后的 schema 策略下保持可用，且不再创建或依赖 M04 的身份与所有权表。

# Constraints and invariants

- 不使用 `git reset`、`git checkout` 或全仓删除；工作树包含用户与已归档配置 change 的独立改动。
- 仅按 M04 归档的 implementation scope 反向处理对应文件，遇到与保留配置 change 共享的文件时实施最小手工回退。
- 数据库操作必须限制在已明确的 VenAgent 本地数据库，并在执行不可恢复删除前获得用户确认。

# Decisions

- 用户确认放弃 M04 用户模块，除 Vite 代理从 `8000` 改为 `8090` 外回退 M04 实现。
- 用户确认保留 PostgreSQL YAML 配置、密码注入、Docker 服务和 `8090` 后端端口。
- 用户选择 B：在代码回退完成后，删除并重建 Docker PostgreSQL 容器内的 `venagent` 数据库；所有该库中的对话、checkpoint、用户与会话数据均不可恢复。随后只通过 `python -m venagent migrate` 创建回退后的 M03 schema。
- 用户最终确认回退契约。

# Open questions

- 无。

# Verification expectations

- 验证 M04 路由与前端账户表面已移除，M03 匿名聊天和 legacy import 行为恢复。
- 在 Docker PostgreSQL 上验证回退后的 migration/schema 与重启恢复；运行 Python、前端构建和针对性浏览器测试。
