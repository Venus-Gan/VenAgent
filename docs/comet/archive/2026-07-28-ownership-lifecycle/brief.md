# Outcome

实现 M04 `ownership-lifecycle`：匿名聊天始终可用，注册账号可选；所有服务端 thread、运行和历史都绑定权威 `owner_id`，使用短期访问 JWT 与可撤销 refresh 会话完成鉴权，并为匿名保留、跨设备账号历史、标题、硬删除、PostgreSQL 降级和 LangGraph checkpoint 一致性提供完整前后端契约。

# Scope

- 提供临时匿名、持久匿名和注册账号三种运行身份，所有 conversation 与 run 操作均由服务端校验 actor/owner，不把 `thread_id` 当作凭据。
- 提供用户名/密码注册、登录、当前身份、访问令牌刷新、退出当前会话、修改密码和注销账号；用户模块保持基础，不增加资料、角色或找回能力。
- 提供账号历史跨浏览器恢复、线程游标分页、成功消息读取、自动标题、手动重命名和硬删除；失败、取消、partial 只保留在当前浏览器。
- 为匿名 thread 定义 7 天保留、小时级清理、活跃运行避让、删除重试、限额与 `local_only` 本机历史行为。
- 把 VenAgent 业务历史设为事实源，把 LangGraph checkpoint 设为最近五个已提交轮次的运行投影，并定义 pending/version 修复与幂等提交协议。
- 将 schema 从 v3 升级到 v4；升级时永久删除全部无 owner 的旧 thread 和 checkpoint，包括通过公共 checkpointer 枚举发现的孤儿状态。
- 在现有 Vue 聊天工作区加入账户面板、认证弹窗、身份启动门、服务器历史、本机历史、降级弹窗及完整错误/加载/移动端行为。
- 修订 `conversation-persistence` 的完整目标规格，使 M03 的持久化事实与 M04 新增的 owner、业务历史和 v4 迁移一致。

# Non-goals

- 不实现邮箱、验证、密码找回/重置、SSO、MFA、角色、组织、设备管理、管理员后台或账号资料页。
- 不实现搜索、文件夹、归档、分叉、分享、导入导出、实时跨设备同步或复杂会话库。
- 不迁移、认领或上传匿名对话到注册账号；登录和注册后的账号历史从零开始。
- 不实现 refresh token family 盗用检测、设备异常分析、JWKS/非对称密钥、自动密钥轮换或外部认证服务。
- 不实现多 Uvicorn worker、多实例锁、跨实例取消或分布式清理；这些平台治理能力留给 M09。
- 不实现 M05--M09 的记忆、工具、编排、RAG 或管理侧配额/运营策略。
- 不把 AGI-saber 的 Go 架构、表结构、7 天 access JWT、前端 `localStorage` token 或强制登录覆盖层迁入 VenAgent。

# Acceptance examples

- 新浏览器无需登录即可取得 guest actor、创建/流式聊天/取消/删除；访问 JWT 只在内存，refresh 凭据只在 HttpOnly Cookie，猜测其他 owner 的 `thread_id` 或 `run_id` 始终得到不泄露存在性的 404。
- 两个隔离浏览器上下文登录同一账号后能看到相同的已提交 thread、标题和成功轮次；失败、取消和 partial 消息不出现在另一浏览器。
- 登录或注册会撤销当前 guest 会话但不迁移匿名 thread；匿名本地记录转为“仅本地”，登录时隐藏，退出后以全新 guest 身份重新显示且仍不可继续发送。
- guest thread 仅在完整成功提交后续期；失败、取消、查看、刷新和创建空 thread 不续期。到期清理避开 active run，最多延后一轮小时级 sweep。
- PostgreSQL、schema 或持久认证配置在启动时不可用时，进程固定进入临时匿名模式；聊天仍可用，用户点击任何账号操作均看到明确弹窗，账号 Cookie 保持休眠且不会被误清除或降级成假登录。
- 同步和 SSE 仅在业务 turn 已提交、checkpoint 投影一致、标题和成功时间已更新后返回成功/`completed`；任一步失败都不形成跨设备可见成功，重启可从 committed history 修复 checkpoint。
- 单 thread 删除和账号注销都先禁止访问/新运行，再通过公共 `delete_thread` 清理 checkpoint，最后删除业务记录；中断后重试，删除对象不会恢复可用。
- v3→v4 迁移在独占维护边界内删除所有旧 thread 及孤儿 checkpoint；任一清理或 DDL 失败都不记录 v4，普通 durable 启动拒绝该 schema，旧浏览器记录只转为本机只读。
- 手动标题为 1--100 字符、允许重复，失败时乐观 UI 回滚；手动标题一旦成功，自动标题不再覆盖。

# Constraints and invariants

- `owner_id`、`thread_id`、`run_id`、`session_id` 和 `client_message_id` 职责不同，不得互作授权凭据或复用。
- 所有权过滤必须在 conversation/ownership 用例和仓储查询中执行；HTTP 仅解析凭据与映射协议，`infra/` 不承载业务决策。
- account 与 guest access JWT 固定 15 分钟、固定算法，并校验 `iss`、`aud`、`sub`、`jti`、时间、actor kind 和 session；签名有效仍须回查 session 与 owner active 状态。
- account refresh 会话固定 30 天且轮换不延长；guest session/thread 的 7 天期限只由完整成功提交推进。服务端只保存 refresh hash。
- 用户名按 NFKC + casefold 建唯一键，显示值保留裁剪后的输入；密码不 trim、长度 8--128，不设组合规则并使用成熟自适应哈希实现。
- 成功历史只有完整 user/assistant 对；业务 history 是事实源，checkpoint 只保留最近五轮投影，不直接查询或修改 LangGraph 物理表。
- durable 运行中数据库故障不得热切到内存形成第二份所有权状态；临时匿名模式只在启动时选择，恢复 durable 需要重启。
- 账号注销的远端擦除边界是服务端管理数据与当前可达浏览器；离线其他浏览器无法远程擦除，只能在下次联机校验失败后清理。
- Cookie 状态变更端点必须校验精确 Origin/CSRF 边界；CORS 不允许带凭据的通配来源；任意代理头只在显式可信代理配置下使用。
- M04 只支持单 API 进程。实现可在 Build 中按内聚性合并或拆分 `.py`/Vue 文件，但不得改变已确认的 package 职责和依赖方向。
- 保持 M01--M03 的线程隔离、单线程单活跃运行、SSE 唯一终态、取消、断开不提交、最近五轮上下文和稳定错误语义。

# Decisions

- 匿名聊天始终可用，账号是可选增强；不再采用“认证服务不可用就完全阻断聊天”的方案。
- 匿名 actor 由服务端创建并使用独立 guest refresh Cookie；账号与临时匿名使用不同 Cookie/身份，任一时刻只有一个 active access actor。
- 注册自动登录；登录/注册不认领匿名记录。退出仅撤销当前账号 session，并创建一个全新的 guest。
- access JWT 只进入前端内存与 `Authorization: Bearer`；refresh 使用随机不透明凭据和 HttpOnly/Secure/SameSite Cookie。HS256 强随机秘密满足首版，claims 不含用户名或敏感数据。
- refresh 轮换保留一个短暂、受限的“上一 hash”并发宽限，只用于吸收同一浏览器多标签并发；前端仍使用 single-flight 与浏览器标签协调。
- 账号对话不自动过期；匿名每个 thread 独立按 `last_successful_at` 或 `created_at` 计算 7 天期限，sweeper 每小时运行。
- 匿名默认最多 10 个 live server thread、10 分钟最多创建 5 个；本机只读记录不计入。认证入口另有基础暴力尝试限流。
- 服务端已删除/过期的匿名记录不从浏览器自动删除，而是标记 `local_only`、“仅本地”、只读，等待用户主动删除。
- 账号历史由后端 committed turns 权威提供；当前浏览器可缓存账号历史，但身份无法验证时不得展示，显式退出清除该账号缓存。
- 自动标题在首个成功轮次后由首条成功用户消息生成；手动标题允许重复并永久压过自动标题。
- 采用 pending turn → checkpoint 投影 → committed turn/线程元数据的提交协议；`client_message_id` 唯一约束用于安全重试与去重。
- 账号注销采用 `deleting` 内部状态：立即不可访问、取消 active run、撤销全部 session、返回 202，再可重试地清理 checkpoint 与业务数据，不提供恢复期。
- M04 v4 迁移永久删除所有 v3 无 owner thread/checkpoint，不尝试从 checkpoint 反推历史或所有者。
- 目录职责采用最小 feature 增量：新增 `venagent/ownership/` 与 `web/src/modules/ownership/`；conversation 拥有历史/标题/turn 生命周期；`infra/security/` 实现 JWT/密码 adapter；`infra/platform/` 实现 PostgreSQL/内存/migration；HTTP 保持薄层。具体文件名不钉死。
- 模块 intake：已读取 `ecc-rules-pack-common`、`ecc-rules-pack-python`、`search-first`、`venagent-module-router`、`api-design`、`security-review`、`product-capability` 与 `langgraph-persistence`。
- search-first：仓库搜索、项目 venv、pip/npm 与本地 Skill 可用；GitHub CLI 缺失，PyPI shell 查询受网络策略阻断，官方 Web 通道返回 404，均按不可用记录。已核对当前 venv 的 LangGraph 1.2.9 / checkpoint-postgres 3.1.0 公共 `list` 与 `delete_thread` API。结论为 Compose：采用成熟 JWT 与 Argon2 密码库，组合项目自有 owner/session/commit 用例，不自制密码算法或 JWT 解析器。
- AGI-saber 对照范围：优先读取 `internal/domain/auth`、`internal/application/auth`、`internal/usercontext`、`internal/infrastructure/persistence/userrepo`；为确认 HTTP/前端行为最小扩展到 auth middleware/handler/tests 和 `web/src` 的 auth store、client、AuthModal、SideBar、App。采用稳定错误、强密钥、dummy 密码比较、请求身份与隔离测试；舍弃本地 token、长 access JWT、客户端 logout 和未回查 session 的方案。
- product-capability 结论：M04 已达到可直接实现的 capability contract；不新建全局 auth 平台、RBAC、组织、管理后台、未来模块共享层或空 UI。
- 用户最终确认：以本 brief、`ownership-lifecycle` 和修订后的 `conversation-persistence` 完整目标规格作为 M04 Build 契约；Build 可调整具体文件拆分，但不得改变匿名/JWT/账号/历史/删除/checkpoint/v4 迁移/UI/单进程边界。

# Open questions

- 无。

# Verification expectations

- 使用 `.venv\Scripts\python.exe -m pytest -q` 运行全量 Python 回归，并补充 ownership、JWT/session、owner 隔离、历史、标题、TTL、限流、降级、删除与 checkpoint 修复的单元/API 测试。
- 使用隔离 PostgreSQL 验证 v3→v4、约束/索引、公共 checkpointer 孤儿枚举清理、未知新版本拒绝、迁移失败不记 v4、pending/checkpoint/commit/delete 各故障点的收敛。
- 使用 fake model、fake clock 和受控 adapter 验证同步/SSE 完成、取消、异常、断连、重复 `client_message_id` 与 active-run 到期竞态；不调用真实外部 LLM。
- 在 `web/` 运行 `npm.cmd run build` 与 `npm.cmd run test:e2e`；Playwright 使用两个隔离 browser context 覆盖跨浏览器历史，并覆盖匿名、账号、临时模式、local-only、重命名、删除、JWT 刷新、401/404/409/429/503、移动抽屉与键盘焦点。
- 以桌面和移动端截图检查账户面板、对话列表、弹窗、只读横幅和文本无重叠；验证启动身份解析期间无错误身份闪烁。
- Ruff、mypy、Bandit、依赖审计等只在已安装且能提供有效证据时运行；不可用或跳过必须如实记录，不替代项目原生测试。
