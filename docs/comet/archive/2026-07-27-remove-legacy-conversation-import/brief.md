# Outcome

删除 M03 的浏览器旧会话导入能力。浏览器 localStorage 中的会话一旦被后端以 `thread_not_found` 判定为失效，前端仍可显示其本地记录，但该会话永久处于不可用只读状态，不再提供恢复或导入路径。

# Scope

- 移除 Vue 前端和兼容静态前端中的“导入旧会话”按钮、确认流程与 `/api/threads/import` 请求。
- 移除后端旧会话导入 HTTP schema、路由、业务服务、校验模型、错误类型、repository port 和 PostgreSQL 导入实现。
- 从健康响应中移除 `legacy_browser_import` 能力字段。
- 增加显式 PostgreSQL schema migration，删除不再使用的 `conversation_imports` 映射表；保留对遗留 `importing` 线程的启动清理兼容。
- 浏览器记录收到 `thread_not_found` 后标记为失效；消息可继续查看，会话可从本地列表删除，但发送、重试、恢复和导入均不可用。
- 失效会话在列表中显示“不可用”，打开后持续显示状态横幅：“后端上下文已失效。此对话仅保留在当前浏览器中，只能查看或删除，无法继续发送消息。”
- 更新 Python 与 Playwright 回归测试，并把 M03 完整目标规格改写为不包含旧会话导入的最终行为。
- 同步改写 `frontend-foundation` 与 `skill-orchestration` 完整目标规格，移除其对旧会话导入的过期强制要求，统一为失效会话不可用提示与浏览器操作验证。

# Non-goals

- 不删除已经成功导入且当前仍是正常 `active` durable thread 的会话或 checkpoint。
- 不自动删除、隐藏或上传浏览器 localStorage 中的旧消息；用户仍可查看和手动移除本地记录。
- 不新增服务端会话列表、历史读取、修复、认领、归档、导入导出或跨设备同步能力。
- 不改变 M01/M02 的同步聊天、SSE、取消、线程隔离和最近 5 个成功轮次契约。

# Acceptance examples

- 当前会话发送消息时后端返回 `thread_not_found`，前端保留已有消息并将会话显示为不可用；输入框、发送、失败消息重试和任何导入操作均不可用。
- 失效会话的列表项显示“不可用”；选择该会话后，消息区上方持续显示只读原因和允许操作，不依赖短暂 toast。
- 刷新页面后，已标记失效的 localStorage 会话仍保持不可用只读状态，不会因 PostgreSQL durable 模式可用而出现导入按钮。
- 用户可以删除失效会话；后端重复删除保持 HTTP 204，本地记录随后从列表移除。
- `POST /api/threads/import` 不再存在并返回 HTTP 404，OpenAPI 不再公开该路径。
- 新 schema migration 删除 `conversation_imports` 表；既有 active durable threads 在迁移和重启后仍可继续聊天，遗留 importing/deleting 状态仍能安全收敛。
- `/health` 继续准确公开 chat 与 conversation persistence，但不再包含 legacy browser import capability。

# Constraints and invariants

- localStorage 只是可见记录，不是后端上下文事实源；后端校验失败后不得用本地消息重建或伪装有效上下文。
- `thread_not_found` 是将本地记录转为不可用状态的权威信号；普通网络错误、模型错误和取消不得误标记为失效会话。
- 已失效会话不得再触发聊天、重试或恢复请求；刷新后状态必须保持。
- 已成功导入的 active durable thread 与普通 active thread 等价，不因移除导入功能而失效。
- schema 变更必须显式、可重复执行且保持连续版本；普通启动不执行 DDL。
- 遗留 `importing` 线程仍由启动恢复逻辑通过公开 checkpointer API 清理，避免遗留 checkpoint。

# Decisions

- 用户明确要求删除旧对话导入功能，并要求浏览器本地记录与后端校验失败后，前端显示的旧对话不可用。
- “不可用”定义为：仍可查看消息和从本地删除，但不能发送、重试、恢复或导入。
- 前端使用持续状态横幅提示失效原因、数据仅保存在当前浏览器以及允许的查看/删除操作，并在会话列表显示“不可用”。
- 删除导入能力不追溯删除已经成功转为 active durable thread 的历史会话。
- 使用新 schema version 删除 `conversation_imports`，而不改写既有 v1/v2 migration 历史。
- 用户已确认提示位于对话标题下方、历史消息列表上方，桌面端和移动端位置一致，并批准进入实现；验收必须模拟真实用户操作确认最终效果。
- 用户已再次确认将 `frontend-foundation` 与 `skill-orchestration` 的相邻规格同步纳入本 change，消除其对旧会话导入的过期要求。

# Open questions

无。

# Verification expectations

- Python API 测试证明导入路由和 OpenAPI 表面已移除，未知导入请求返回 404。
- persistence 测试证明 v1/v2 到新版本的显式迁移、映射表删除、active thread 保留和遗留 lifecycle 清理。
- Vue 单元/构建与 Playwright 场景证明失效会话刷新后仍只读，列表和状态横幅提示准确，无导入入口，不可发送/重试且可删除。
- 运行项目相关 pytest、前端构建和有针对性的 Playwright；记录实际跳过项和 PostgreSQL 可用性。
- 执行针对 Python、FastAPI 和边界删除的人工复核，确认无残留导入 API、错误映射、健康能力或死代码。
- 扫描 canonical specs，确认相邻前端与模块编排契约不再要求旧会话导入。
