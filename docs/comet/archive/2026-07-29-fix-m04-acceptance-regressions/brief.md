# Outcome

修复 M04 实际浏览器验收暴露的身份、流式终止、checkpoint 与长文本布局不一致，同时删除“本机历史”能力，使基础用户模块在登录、退出、注销、取消、断流和重试路径上具有一致且可自动回归的前后端行为。

# Scope

- 删除前端 `local_only`、`anonymous_local`、本机历史分区和旧本机历史迁移；当前 owner 的失败、取消和 partial 仍可作为 server thread 浏览器缓存用于刷新后重试。
- 统一登录、注册、退出、注销、401 降级和跨标签页身份变化；标签间只发送非敏感失效通知，旧 owner 内容先清除再 refresh。
- 为 SSE 增加 heartbeat、无终态 EOF/读取错误/活动超时收敛和完整资源清理。
- 区分发送中、思考中、生成中、已停止、连接中断与失败；重试保持 `client_message_id` 幂等。
- 正常一致 thread 不再运行写入型 `_repair`；真实修复通过公开 `delete_thread` 清链后按 committed turns 重建。
- 固定桌面和移动端聊天网格，使长文本只滚动消息区且 composer 始终可见。
- README 默认启动入口和端口改为 `python -m venagent` / `8090`。
- 更新所有权、流式、持久化、前端和配置完整目标规格及相应测试。

# Non-goals

- 不管理或自动清理空的服务端 thread。
- 不解决第三方模型或网关合并 token 导致的伪流式体验。
- 不改变“后端不可用期间，本机中断消息暂时不可见、恢复后重新出现”的既有边界。
- 不扩展密码、邮箱、找回、MFA、设备管理、管理员、跨设备实时同步或 M05--M09 能力。
- 不新增数据库表或 migration，不修改生产 HTTPS/部署策略。

# Acceptance examples

- 同源两个标签页登录同一账号；任一标签退出或注销后，另一标签立即停止活动流、清除账号历史与消息，并在 refresh 后显示新 guest 身份。
- SSE 只返回 `started`/partial 后直接 EOF，或连接长时间没有 token/heartbeat；UI 最终显示“连接已中断”和重试，不残留 busy。
- 用户在首 token 前或生成中停止；用户消息保持已发送，assistant 显示“已停止生成”，partial 可见且重新生成最终只形成一个 committed turn。
- 一致 thread 上取消、模型错误与断流前后 checkpoint 数量不增加；pending/version 故障修复后旧 checkpoint 链和幽灵内容不存在，最新投影只含最近五个 committed turn。
- 后端返回 `thread_not_found` 后前端移除引用并提示，不出现“本机历史”或“仅本地”记录。
- 桌面和 390px 移动视口生成长文本时 composer 始终在视口内，消息区域独立滚动。
- README 的默认命令启动 8090，与 Vite 代理一致。

# Constraints and invariants

- 服务端 committed turns 是业务事实源；浏览器缓存和 LangGraph checkpoint 都不得提升为业务事实。
- access JWT 只在内存持有，不进入 localStorage、BroadcastChannel、日志、URL 或错误。
- 身份变化时隐私优先：上一 owner 的未提交本机失败/partial 可以丢弃，不得继续显示。
- `thread_not_found` 保持不泄露资源存在性的 owner-scoped 404；普通网络、模型、取消、409、429 或 503 不得删除 thread 引用。
- SSE heartbeat 不属于业务事件，不改变业务 sequence，也不得进入回答文本。
- 仅使用 LangGraph 公开 state/checkpointer API；不查询或修改其物理表。
- 不新增 feature 目录或共享层；扩展现有 `web/src/modules/chat`、`web/src/modules/ownership`、`venagent/conversation`、`venagent/interfaces/http` 与 adapter。

模块 intake：

- 模块：M04 ownership-lifecycle。
- 基础 intake：已读取并应用 `ecc-rules-pack-common`、`ecc-rules-pack-python`、`search-first`；仓库检索、npm、pip 和官方 Web 文档可用，GitHub CLI 与独立 researcher/MCP docs 渠道不可用并已如实排除。
- 专项能力：`api-design` 用于保持现有状态码和错误 envelope；`security-review` 用于 token/跨标签隐私；`frontend-patterns` 用于 Pinia 状态收敛和响应式布局；`ecosystem-primer` 后接 `langgraph-persistence` 用于 checkpoint 公共 API。
- search-first：检索当前 Vue/Pinia、Fetch/SSE、FastAPI、LangGraph 实现与测试，并核对当前官方 LangGraph persistence/delete API；结论为 Extend，现有依赖完整，不安装新包。
- AGI-saber：对照身份上下文、认证应用服务、用户仓储与 JWT 安全边界。
- AGI-saber 范围：仅 `internal/domain/auth`、`internal/application/auth`、`internal/usercontext`、`internal/infrastructure/persistence/userrepo` 及测试；信息充分，无扩展路径，不迁移 Go 代码或表结构。
- 目录：只修改既有模块与测试，不新增/迁移 package、Vue module、路由或共享表面，因此不触发额外目录规划。
- 前端：覆盖身份/匿名、加载、正常、发送、思考、生成、停止、中断、失败、重试、404、离线降级和无权内容清除；通过 Playwright 双标签、EOF、取消、长文本桌面/移动路径验证。

# Decisions

- 用户确认彻底移除“本机历史”，而不是修复 `local_only` 记录的可访问性。
- 用户确认空服务端 thread、供应商流式缓冲和后端不可用期间本机中断消息隐藏暂不处理。
- 用户确认其余验收问题按本 brief 直接实现，只有新业务决策才暂停。
- checkpoint 修复采用“按需检测，公开 delete 后重建”，正常运行前不写 checkpoint。

# Open questions

无。

# Verification expectations

- Python 单元/集成测试覆盖 repair 判断、checkpoint 数量/内容、heartbeat、断开、取消与资源释放。
- Playwright 覆盖双标签身份失效、无终态 EOF、取消状态、重试幂等、无本机历史、404 移除、账号注销 UI 和长文本桌面/移动布局。
- 运行全量 pytest、Vue 类型检查与生产构建、Playwright E2E、Comet 内置检查和 diff/text hygiene。
- PostgreSQL 可用时运行真实 adapter 的定向一致性验证；若环境不可用必须记录跳过，不得声称通过。
