# 所有权与身份生命周期

## 1. 能力目标与边界

VenAgent SHALL 在不阻断匿名聊天的前提下提供可选的基础账号能力。每个服务端对话、运行、成功历史和会话 SHALL 归属于权威 `owner_id`；服务端 SHALL 在业务边界执行身份与所有权校验，不得把 `thread_id`、`run_id` 或不可预测 UUID 当作授权凭据。

M04 SHALL 交付匿名身份、注册账号、短期 JWT、可撤销 refresh 会话、跨浏览器账号历史、标题、硬删除、匿名保留与降级体验。M04 是 M05 及一切按用户存储或访问数据能力的前置条件。

M04 SHALL NOT 实现邮箱、验证、密码找回/重置、SSO、MFA、角色、组织、设备管理、管理员后台、用户资料、会话搜索/文件夹/归档/分叉/分享/导入导出、实时跨设备同步或 M05--M09 能力。

## 2. Actor、身份模式与状态

系统 SHALL 区分以下 actor：

- `guest`：PostgreSQL durable 模式中的持久匿名所有者，有服务端 guest session、独立 thread 和 7 天保留规则。
- `user`：注册账号所有者，有用户名、密码摘要、可撤销账号 session 和不自动过期的 thread。
- `temporary_guest`：启动时 PostgreSQL、schema 或持久认证配置不可用时创建的进程内匿名所有者；重启即丢失且不得迁移到 durable 状态。

任一 HTTP 请求最多 SHALL 有一个 active access actor。账号、持久 guest 与 temporary guest 的 refresh Cookie/身份 SHALL 分离；degraded 模式不得消费、覆盖或删除休眠的账号 refresh Cookie。

`owners.lifecycle_state` SHALL 至少有 `active` 与 `deleting`。`deleting` owner、已撤销/过期 session 或已经删除的 owner SHALL 立即拒绝新的读取、运行、刷新和写入，即使 access JWT 签名及 `exp` 仍有效。

## 3. 访问 JWT 与 Refresh 会话

### 3.1 Access JWT

- `guest`、`user` 与 `temporary_guest` SHALL 使用 15 分钟 access JWT；前端只在内存持有，并通过 `Authorization: Bearer` 发送。
- access JWT SHALL 使用成熟 JWT 库和固定允许算法。首版 MAY 使用 HS256，但秘密必须来自配置、解码后至少 32 个随机字节，不得硬编码或进入日志/错误。
- 验证 SHALL 固定算法并校验 `iss`、`aud`、`sub`、`jti`、`iat`、`exp`、actor kind 与 `session_id`；claims SHALL NOT 包含用户名、密码、refresh 凭据或消息内容。
- `sub` SHALL 是 `owner_id`。签名验证后，服务端仍 SHALL 回查 session 未撤销/未过期且 owner 为 `active`，不得只信任 claims。
- access token 响应 SHALL 使用 `Cache-Control: no-store`，不得写入 URL、日志、`localStorage` 或 `sessionStorage`。

### 3.2 Refresh 凭据

- refresh 凭据 SHALL 是密码学安全的随机不透明值，不是长效 JWT；服务端只保存不可逆 hash。
- Cookie SHALL 为 HttpOnly、SameSite=Strict、无 Domain，并在安全部署中使用 Secure；Path 和删除属性 SHALL 保持一致。开发配置不得放宽生产 Cookie/CORS 规则。
- 账号 session 从创建起固定 30 天；refresh 轮换 SHALL NOT 延长该 `expires_at`。
- 持久 guest session 的 7 天期限只在完整成功 turn 提交后推进；创建 thread、失败、取消、partial、页面查看、刷新和 access refresh 均不得推进业务期限。
- Cookie 的浏览器到期时间 SHALL 在每次合法 refresh 时与服务端当前 `expires_at` 对齐；这只同步已有期限，不构成业务续期。
- 每次正常 refresh SHALL 轮换当前凭据。为吸收同一浏览器多标签并发，服务端 MAY 在短暂有界窗口内接受紧邻的上一 refresh hash，但该路径不得再次轮换 Cookie 或延长期限；更早 hash、窗口外重放和撤销 hash必须失败。
- 前端 SHALL 对 refresh 实施 single-flight，并在可用时通过浏览器标签协调避免并发刷新；服务端宽限不是无限重放或设备管理机制。

### 3.3 浏览器请求边界

- 所有使用或改变 refresh Cookie 的端点，以及登录、注册、退出、改密和注销，SHALL 校验 `Origin` 是否精确命中配置 allowlist；缺失或不匹配 SHALL fail closed。
- CORS SHALL 只允许明确来源、方法和 header；携带凭据时不得使用 `*`。
- client IP 限流仅 SHALL 使用直接对端地址；只有来自显式可信代理时才可解析代理头，不得信任任意 `X-Forwarded-For`。

## 4. 基础账号能力

### 4.1 用户名与密码

- 注册和登录 SHALL 使用用户名与密码。注册成功 SHALL 自动登录。
- 用户名先裁剪首尾空白，再使用 Unicode NFKC + casefold 生成 `username_normalized`；该值 SHALL 唯一。显示值 SHALL 保留裁剪后的原始大小写与 Unicode 形式。
- 规范化后的用户名 SHALL 为 3--32 个 Unicode 字符，只允许 Unicode 字母、数字、下划线和连字符。用户名不可修改。
- 密码 SHALL 为 8--128 个 Unicode 字符，不 trim、不要求字符组合并允许粘贴。密码和确认字段只在提交所需时间存在于内存。
- 密码 SHALL 使用成熟的自适应密码哈希实现，首选 Argon2id；不得自制哈希、保存明文或使用通用快速 hash。
- 不存在账号与错误密码 SHALL 执行等价密码校验成本，并统一返回“用户名或密码错误”；重复注册 MAY 明确返回用户名已存在。

### 4.2 Session 操作

- 登录 SHALL 创建新的账号 session；退出 SHALL 只撤销当前账号 session，并向由该 session 启动的 active run 发出取消。
- 修改密码 SHALL 要求当前密码。成功后 SHALL 更新密码摘要、撤销其他账号 session、取消由被撤销 session 启动的 active run、轮换当前 session，并返回新的 access JWT。
- 登录或注册时，当前 guest session SHALL 被撤销并取消由它启动的 active run；其 server thread 不迁移、不认领，继续按原 TTL 清理。当前浏览器 SHALL 清除该 guest 的对话缓存，不得转为本机历史或 `local_only`。
- 退出账号 SHALL 清除当前账号浏览器缓存，撤销当前 session，并创建全新的 guest actor；不得恢复此前被撤销的 guest 服务端身份。
- 长期未登录账号和账号 thread SHALL NOT 自动清理。

### 4.3 账号注销

- 注销 SHALL 要求当前密码和独立二次确认。
- 接受请求后，系统 SHALL 原子地把 owner 标为 `deleting`、禁止访问与新运行、向该 owner 的 active run 发出取消、撤销全部账号 session，并清除当前浏览器身份。
- 初始请求 SHALL 返回 HTTP 202 与稳定状态 `account_deletion_started`；该返回不声称全部物理清理已同步完成。
- 后台/启动恢复 SHALL 逐 thread 调用公开 checkpointer `delete_thread(thread_id)`，再删除 turns、threads、sessions、user 和 owner 记录。数据库级联不得替代 checkpoint 清理。
- 任一步失败 SHALL 保持 owner 不可访问并可重试；不得恢复为 active，也不提供撤销或恢复窗口。
- 删除保证覆盖服务端主数据与当前可达浏览器。离线其他浏览器不能被远程擦除；它们 SHALL 在下次联机身份校验失败后隐藏并清理账号缓存。

## 5. 匿名身份、保留与防滥用

### 5.1 所有权与恢复

- 首次匿名启动 SHALL 由服务端创建 `guest_owner_id` 和 guest session；浏览器不得自行指定 owner。
- guest Cookie 丢失、清除、撤销或过期后，旧 server thread SHALL NOT 通过 `thread_id` 恢复、认领或重新绑定。
- 匿名 thread SHALL 仅属于创建它的 guest owner；所有查询和变更必须同时限定 `owner_id` 与资源 ID。
- 注册账号 SHALL 从空账号历史开始，匿名 turn/thread 永不迁移到账号。

### 5.2 七天期限

- 每个 guest thread SHALL 独立计算删除期限：有成功提交时为 `last_successful_at + 7 days`，否则为 `created_at + 7 days`。
- guest session SHALL 从 guest 创建时间起计算初始 7 天期限，并只在该 guest 任一完整成功 turn 提交后滑动到 `successful_at + 7 days`。
- “成功”只指业务 turn 已 committed、checkpoint 投影一致并已形成同步成功或 SSE `completed`；模型完成但持久化失败不得续期。
- sweeper SHALL 每小时扫描一次。到期 thread 若有 active run SHALL 暂时跳过；运行成功则按成功时间续期，失败/取消且原期限已过则在下一轮删除。
- 删除 SHALL 使用 `deleting`、公共 checkpoint 清理和可重试收敛；清理延迟最多为正常的一轮 sweep 加当前 active run 收口时间。
- guest 最后一个 thread 清理后，过期/撤销且无引用的 guest session 与 owner SHALL 一并回收。

### 5.3 限额

- 每个 guest 默认最多拥有 10 个 live server thread；每个 guest 默认 10 分钟最多创建 5 个 server thread。
- 浏览器缓存不计入 server 限额。服务 MAY 叠加基于可信 client IP 的粗粒度限流。
- 超限 SHALL 返回 HTTP 429、稳定 code `anonymous_limit_exceeded` 和可用的 `Retry-After`/重试时间，不得伪装为创建成功。
- 登录与注册 SHALL 有基础的按可信 client IP 及规范化用户名的暴力尝试限流；限流不得泄露账号是否存在。

## 6. 对话、历史与标题

### 6.1 Owner-scoped 对话

- 创建、列表、读取、同步聊天、流式聊天、取消、重命名与删除 SHALL 接收服务端解析的 actor，并在 conversation 用例及仓储查询中执行 owner 过滤。
- thread 查询/更新 SHALL 以 `(owner_id, thread_id)` 限定。其他 owner、已过期或不存在的 thread 均返回现有 `thread_not_found`；不得泄露资源存在性。
- run SHALL 记录 owner/thread 归属。取消其他 owner 或未知/已结束 run 均返回现有 `run_not_found`。
- guest 与 user 均可列出当前 server thread；账号历史以服务端为权威，持久 guest 历史只可由当前 guest session 访问。

### 6.2 业务历史

- `conversation_turns` SHALL 保存完整成功的 user/assistant 对，并成为跨设备读取与 checkpoint 修复的业务事实源。
- 只有 `committed` turn 可进入列表、历史响应、标题生成、`last_successful_at`、账号跨浏览器恢复和模型上下文。
- failed、cancelled、断开、pending user 与 partial assistant SHALL NOT 成为 server 历史；前端 MAY 在当前浏览器把它们保存为明确的本地失败/取消状态。
- thread 列表 SHALL 使用稳定的 `(updated_at DESC, thread_id)` 游标分页；cursor 不透明、输入有界且始终绑定当前 owner。默认页大小 20，最大 100。
- thread 读取 SHALL 返回元数据及按 `sequence` 正序的 committed turns；不得返回 pending turn 或内部 checkpoint/version 字段。
- 跨设备不做实时推送。前端 SHALL 在登录、窗口重新获得焦点、成功 turn、重命名、删除及用户手动刷新后重新获取服务端历史。

### 6.3 标题

- 新 thread 初始标题 SHALL 为“新对话”。首个成功 turn 提交时，若标题仍非手动，服务端 SHALL 从该 turn 的用户文本生成自动标题。
- 自动标题 SHALL 裁剪首尾空白、把连续空白折叠为单个空格、保留 Unicode/大小写/标点，并截取前 28 个 Unicode 字符；超出时追加省略号。
- 手动标题 SHALL 为裁剪后 1--100 个 Unicode 字符，不允许换行或控制字符；内部空白、大小写、Unicode 与标点保留，重复标题允许。
- 重命名 SHALL owner-scoped。active/busy thread MAY 重命名；`deleting`、已删除或其他 owner thread不得重命名。
- 手动重命名成功后 `title_source=manual`，后续自动标题不得覆盖。前端 MAY 乐观更新，但失败必须回滚并呈现错误。

### 6.4 删除与浏览器缓存

- 单 thread 删除 SHALL 为不可撤销硬删除且无恢复窗口。active run 保持现有 HTTP 409 `thread_active`。
- 前端不提供独立“本机历史”或 `local_only` 对话。服务端删除成功或返回稳定 `thread_not_found` 时，前端 SHALL 从当前列表与浏览器缓存移除该 thread 引用，并呈现一次安全提示。
- 浏览器 MAY 为当前已验证 owner 缓存 server thread、草稿及失败/取消/partial 状态，以支持同一身份刷新后查看或重试；这些缓存不得上传为服务端历史，也不得在 owner 变化后保留或显示。
- 登录、注册、退出、注销、跨标签页身份变化或 401 身份降级 SHALL 先取消当前在途读取并立即清除上一 owner 的浏览器缓存，再加载新 actor 的服务端历史。

## 7. 业务历史与 Checkpoint 一致性

### 7.1 职责

- VenAgent 业务 history SHALL 是成功轮次的事实源；LangGraph checkpointer SHALL 只保存最近五个 committed turn 的运行投影。
- VenAgent SHALL 仅通过公开 checkpointer API 读取、更新、列举或删除状态，不得直接查询、修改或建立外键到 LangGraph 物理表。
- `AgentLoop` SHALL NOT 在模型调用内部自行形成最终业务提交。conversation 提交协调器 SHALL 控制业务 turn 与 checkpoint 的成功边界。

### 7.2 提交协议

同步与流式运行 SHALL 先在取得 thread lease 后按 `(thread_id, client_message_id)` 做幂等预检：committed 命中直接重放原结果；pending 命中先执行修复并重新检查；同 ID 不同输入立即冲突。只有没有可重放结果时才调用模型。

模型完整成功后 SHALL 按以下顺序收敛：

1. 生成完整 assistant 文本，但尚不返回同步成功或 SSE `completed`。
2. 以 `(thread_id, client_message_id)` 插入不可见 `pending` turn；唯一约束 SHALL 作为并发请求的最终去重边界。
3. 从 committed history 加当前 pending turn 计算最近五轮投影，并通过公开 LangGraph state API 写入 checkpoint，同时写入对应 `checkpoint_version`。
4. 在数据库事务内把 turn 设为 `committed`，递增/对齐 `history_version`，更新 title、`updated_at` 和 guest `last_successful_at`。
5. 重新确认 thread/owner 仍 active 且版本一致后，才返回同步成功或发送唯一 SSE `completed`。

若步骤 2--5 任一步失败，当前运行 SHALL 形成安全错误而非成功；流式客户端可保留已收到文本但必须标为失败。不得在失败后自动改走同步 API重发。

### 7.3 幂等与修复

- 客户端 SHALL 为每次用户发送生成 UUID `client_message_id`，显式重试同一消息复用该 ID；新编辑/新发送使用新 ID。
- `(thread_id, client_message_id)` 和 `(thread_id, sequence)` SHALL 唯一。
- 已 committed 的同 ID 重试 SHALL 返回原 committed answer；同 ID 但规范化后输入不同 SHALL 返回 HTTP 409 `message_id_conflict`。
- 同步重放 SHALL 返回原 `ChatResponse` 并可标记 `replayed=true`。SSE 重放 SHALL 不调用模型，仍依次发送新的 `started`、至少一个包含原 answer 的 `token` 和唯一 `completed`，并可标记 `replayed=true`，从而保持 M02 协议。
- 在开始新运行、读取模型上下文和启动恢复时，系统 SHALL 通过 thread 级检查判断是否存在 pending turn 或 `history_version/checkpoint_version` 不一致；一致状态不得调用 state update 或制造新 checkpoint。
- 发现 pending 或版本不一致时，系统 SHALL 先通过公开 `delete_thread(thread_id)` 清除该 thread 的 checkpoints 与 writes，再从 committed turns 重建最多最近五轮的权威投影、删除未决 pending 并对齐版本。修复失败 SHALL fail closed，不得继续使用可能包含未提交 turn 的 checkpoint。
- checkpoint 比业务 history 更新但 turn 未 committed 的崩溃场景 SHALL 通过上述重建移除幽灵轮次；业务 history 已 committed 而 checkpoint 落后的场景 SHALL 重建补齐。
- 模型调用开始前的正常一致性检查、取消、连接中断与模型错误 SHALL NOT 新增 checkpoint；只有成功提交或真实一致性修复可以写入投影。

## 8. HTTP 契约

### 8.1 身份 API

M04 SHALL 提供以下最小 API；具体 schema 名称可调整，但路径、语义和状态不得漂移：

| 方法与路径 | 语义 |
|---|---|
| `POST /api/auth/guest` | 创建或恢复允许的 guest/temporary guest，返回 actor 与 access JWT。active account 存在时不得静默切换。 |
| `POST /api/auth/register` | 注册并自动登录；撤销当前 guest，不迁移 thread。 |
| `POST /api/auth/login` | 登录并撤销当前 guest，不迁移 thread。 |
| `POST /api/auth/refresh` | 根据当前模式和 refresh Cookie 轮换/恢复 access actor；durable 模式优先有效账号 session。 |
| `GET /api/auth/me` | 以 Bearer JWT 返回当前已验证 actor，不读取 refresh Cookie。 |
| `POST /api/auth/logout` | 撤销当前账号 session，清账号 Cookie/缓存，并返回全新 guest actor。 |
| `PATCH /api/auth/password` | 校验当前密码、修改密码、撤销其他 session 并轮换当前 session。 |
| `DELETE /api/auth/account` | 校验当前密码与二次确认，返回 202 `account_deletion_started`。 |

身份成功响应 SHALL 至少包含 actor kind、`owner_id`、账号时的显示用户名、access JWT、access expiry 与 `durable|temporary` 模式。refresh Cookie 只通过 `Set-Cookie` 返回。

### 8.2 Conversation API

- 既有 `POST /api/threads`、`POST /api/chat`、`POST /api/chat/stream`、`POST /api/runs/{run_id}/cancel` 与 `DELETE /api/threads/{thread_id}` SHALL 要求 Bearer actor，并保持 M01--M03 的主要成功/SSE 结构；聊天请求新增必填 `client_message_id`。
- 新增 `GET /api/threads?cursor=&limit=` 返回当前 owner 的 server thread 页。
- 新增 `GET /api/threads/{thread_id}` 返回 thread 元数据与 committed turns。
- 新增 `PATCH /api/threads/{thread_id}`，只接受 `title` 重命名。
- 响应 schema SHALL 由 Pydantic 验证，未知字段策略明确，列表参数与正文大小有上界。

### 8.3 稳定错误与缓存

- 错误 envelope SHALL 保持 `{"error":{"code":"...","message":"..."}}`。缺失、非法、过期 access JWT 与 inactive session SHALL 分别使用 401 `access_token_missing|access_token_invalid|access_token_expired|session_inactive`；无 refresh 凭据使用 401 `refresh_required`。
- 登录用户名不存在或密码错误 SHALL 统一为 401 `invalid_credentials`；重复用户名 SHALL 为 409 `username_taken`。guest 调用账号专属 API SHALL 为 403 `account_required`；Origin/CSRF 失败 SHALL 为 403 `origin_not_allowed`。
- thread 与 run 的不存在、过期或跨 owner 访问 SHALL 分别统一为 `thread_not_found`、`run_not_found`；不得以 403 暴露资源存在。
- busy/active/deleting SHALL 保持 409 语义；重复用户名、消息 ID 冲突与身份切换冲突使用稳定 409 code。
- 匿名限额与认证限流 SHALL 返回 429 和 `Retry-After`；账号基础设施不可用 SHALL 返回 503 `account_service_unavailable`，临时匿名聊天不得因此失败。
- auth、history 与 owner-scoped 响应 SHALL 使用 `Cache-Control: no-store`；错误不得包含数据库异常、栈、token、Cookie、密码摘要或账号存在性细节。

## 9. PostgreSQL v4 数据模型

以下表名和职责是维护契约。Build MAY 在不改变约束、所有权与生命周期语义的前提下细化列名。

### 9.1 `owners`

- `owner_id UUID PRIMARY KEY`
- `kind` 仅允许 `guest|user`
- `lifecycle_state` 仅允许 `active|deleting`
- `created_at`、`updated_at`、可空 `delete_requested_at`

### 9.2 `users`

- `owner_id` 为主键并外键到 `owners`
- `username_normalized` 非空唯一，`username_display` 非空
- `password_hash`、`password_changed_at`、`created_at`、`updated_at`
- 数据约束 SHALL 保证 user 行只对应 user owner；应用用例仍须校验，不得只依赖约定。

### 9.3 `auth_sessions`

- `session_id UUID PRIMARY KEY`、`user_owner_id` 外键
- `refresh_hash` 非空唯一；可选上一 hash 与其短暂有效时间
- 固定 `expires_at`、可空 `revoked_at`、`created_at`、`updated_at`

### 9.4 `guest_sessions`

- `session_id UUID PRIMARY KEY`、`guest_owner_id` 外键
- `refresh_hash` 非空唯一；可选上一 hash 与其短暂有效时间
- `expires_at`、可空 `revoked_at`、`created_at`、`updated_at`

### 9.5 `conversation_threads`

- 保留 `thread_id` 与生命周期字段，新增非空 `owner_id` 外键。
- 新增 `title`、`title_source`（`auto|manual`）、可空 `last_successful_at`、`history_version`、`checkpoint_version`。
- 保留 `created_at`、`updated_at`、可空 `delete_requested_at`。
- owner 列表索引 SHALL 支持 `(owner_id, updated_at DESC, thread_id)`；匿名清理索引 SHALL 支持按有效期限和 lifecycle 扫描。

### 9.6 `conversation_turns`

- `turn_id UUID PRIMARY KEY`、`thread_id` 外键、`client_message_id UUID`
- 正整数 `sequence`、`user_content`、`assistant_content`
- `commit_state` 仅允许 `pending|committed`，并保存创建/提交时间
- 唯一 `(thread_id, sequence)` 与 `(thread_id, client_message_id)`；thread 删除级联 turns。

用户名规范化键、refresh hash、owner 列表、匿名期限和 turn 唯一性 SHALL 由数据库约束/索引与用例测试共同证明。数据库不得存 access JWT 或 refresh 明文。

## 10. v3→v4 迁移

- migration SHALL 在显式维护命令中执行，取得数据库级独占迁移锁，并要求没有并发 VenAgent 写入；普通应用启动不得执行 DDL。
- 迁移 SHALL 枚举 v3 `conversation_threads` 的全部 thread ID，并通过公开 checkpointer `list` 枚举可能没有业务 thread 行的孤儿 thread ID。
- 每个发现的 ID SHALL 调用公开 `delete_thread(thread_id)`；不得直接删除或查询 LangGraph checkpoint 物理表。
- 只有全部旧 thread/checkpoint 清理成功后，才可在事务中创建/修改 v4 业务表、约束和索引，并记录 schema version 4。
- 任一枚举、checkpoint 清理、DDL、约束验证或版本记录失败 SHALL 不写 v4 版本；重试必须幂等，普通 durable 启动 SHALL 把该 schema 视为不可用。
- 迁移 SHALL 永久删除全部 M03 无 owner 服务端数据，不从 checkpoint 推断 owner/业务历史。旧浏览器 v1 本机历史 SHALL 被清除，不迁移、不上传且不重新绑定。
- 未知更高 schema version、非连续 migration history 或不满足 v4 约束的数据库 SHALL fail closed。

## 11. 删除与恢复任务

- 单 thread、匿名到期、账号注销和迁移清理 SHALL 共用“先不可访问，再公共 checkpoint 清理，最后业务删除”的不变量。
- 运行中 thread 不得被普通单删；账号注销 SHALL 先请求取消该 owner 的运行并在运行收口后继续物理删除。
- 服务启动和小时级维护任务 SHALL 扫描 `deleting` owner/thread、过期 guest thread、pending turn 与版本不一致状态，并按稳定顺序收敛。
- 清理任务 SHALL 可重复执行，单个对象失败不应把其他对象错误标成完成；失败原因用安全 code/计数记录，不记录消息正文、密码或凭据。
- 当前 M04 只支持单 API 进程；不得通过多 worker 配置声称清理、run registry 或 refresh 宽限在进程间一致。

## 12. 启动降级与健康状态

- 启动时 PostgreSQL 未配置、连接失败、schema 非 v4 或持久认证秘密不可用时，进程 SHALL 固定选择 `temporary` 匿名模式；恢复 durable 必须重启，不做热切换。
- temporary 模式 SHALL 使用进程随机身份/JWT 秘密、内存 thread/history/checkpoint/session；重启全部丢失且永不迁移到 PostgreSQL。
- temporary 模式 SHALL 保持 temporary guest 的创建、access/refresh、聊天、SSE、取消、删除与当前身份浏览器缓存可用；注册、登录、账号 refresh、改密和注销均返回 `account_service_unavailable`。
- 用户点击任何账号入口时，前端 SHALL 显示统一弹窗：持久化当前不可用、账号操作未执行、当前仅为临时匿名、重启可能丢失，并提供继续匿名与重新检查。
- 账号 refresh Cookie SHALL 在 temporary 模式保持休眠；temporary guest 使用独立 Cookie。健康状态 SHALL 公开 `anonymous_chat`、`account_identity`、`conversation_persistence`、mode 与稳定 reason code，不泄露数据库或秘密细节。
- durable 模式运行中 PostgreSQL 故障 SHALL fail closed 并呈现服务失败，不得创建第二份 memory owner/history。

## 13. Web UI 与交互

### 13.1 布局

- 保持现有单一聊天工作区，不新增用户中心或 landing page。
- 侧栏顶部 SHALL 显示模式/身份与新建对话；中部只显示当前 actor 的 server thread；底部显示账号面板。前端 SHALL NOT 提供“本机历史”或 `local_only` 分区。
- 匿名账号面板提供登录/注册；登录后显示用户名、修改密码、退出和注销。
- 窄屏时上述内容随现有可访问抽屉显示；Escape、遮罩关闭、焦点恢复、键盘顺序和屏幕阅读器标签 SHALL 保持可用。

### 13.2 启动与认证弹窗

- 前端 SHALL 在身份 bootstrap 完成前显示稳定加载状态，不先渲染错误的匿名或账号界面。
- 登录/注册 SHALL 使用不阻断匿名聊天的 modal，并明确匿名历史不会迁移；提交登录本身不再增加额外确认。
- 表单 SHALL 有字段校验、提交中禁用、通用登录错误、重复用户名错误和可恢复网络错误；成功或关闭后清空密码。
- temporary 模式下所有账号操作 SHALL 打开统一不可用 modal，不跳转、不提交假请求或伪装成功。

### 13.3 历史与错误状态

- 账号 server history 加载成功后 SHALL 与 owner-keyed 本地缓存协调；服务端是成功 turns/title 的权威，当前浏览器的失败/取消/partial 保持本地状态。
- 身份已验证但 history 暂时失败时，MAY 显示该账号本地缓存，但必须只读并标明离线；身份无法验证时不得显示账号缓存，应隐藏缓存并进入登录/继续匿名流程。
- 显式退出 SHALL 清账号缓存。非显式 refresh 失败可暂存但隐藏本地失败/草稿，只有同一 owner 再次验证后才能显示。
- `thread_not_found` SHALL 删除当前浏览器中的该 thread 引用并显示一次“对话已不存在”提示；普通网络、模型、取消或 503 不得删除 thread 引用。
- UI SHALL 分别处理 401、403、404、409、429、503、refresh 失败、删除中、空列表、分页加载和手动刷新；429 显示可重试时间，409 保留当前数据，401 最多 single-flight refresh 后重试安全请求。
- 对可能已到达服务端的聊天不得无条件自动重发；重试 SHALL 复用 `client_message_id`，并由幂等契约决定返回原结果或继续。
- account 删除完成后清当前浏览器并进入全新 guest；其他浏览器在下次在线校验后清理。
- 同源标签页身份同步 SHALL 只广播“身份需要重新确认”的非敏感信号，不得通过 `BroadcastChannel` 传递 access JWT、refresh 凭据、Cookie 或消息内容。接收标签页 SHALL 在重新 refresh 前同步隐藏并清除旧 owner 内容。

## 14. 安全、日志与可观测性

- 所有输入 SHALL 在 Pydantic/业务边界验证，SQL 使用参数化查询，标题与消息按纯文本渲染；不得把服务端返回文本作为未净化 HTML。
- auth/session/history 响应和错误不得被共享缓存；日志不得记录密码、JWT、refresh、Cookie、用户名、消息内容、连接串、数据库原始错误或栈。
- 结构化日志 MAY 记录 request ID、actor kind、资源操作、稳定结果 code、计数和耗时；删除日志不得成为可恢复账号数据的旁路存储。
- 登录不存在用户与错误密码的响应正文、状态和主要计算成本 SHALL 等价。
- access/refresh、owner 隔离、CSRF/Origin、CORS、可信代理、限流、密码哈希、删除与 checkpoint 修复 SHALL 有正常、失败、边界和竞态测试。

## 15. 最小目录与依赖方向

M04 SHALL 在现有 feature-first 结构上采用以下职责；这是 package/module 边界，不钉死具体 `.py` 或 Vue 文件名：

```text
venagent/
  ownership/                  # owner/user/session/JWT 面向用例、模型、错误与消费方端口
  conversation/               # owner-scoped thread/history/title/turn 生命周期与提交协调
  agent/                      # 纯模型执行与 LangGraph 投影，不自行提交业务成功
  infra/
    security/                 # 密码哈希、JWT、随机 refresh/hash adapter
    platform/                 # PostgreSQL/内存 adapter、v4 migration、启动模式与维护任务
  interfaces/http/            # 薄的身份依赖、Pydantic schema、Cookie/Origin/路由映射
  bootstrap.py                # 唯一 composition root

web/src/modules/
  ownership/                  # 身份 store、账户面板、认证/改密/注销/不可用 modal
  chat/                       # server/local history、标题、消息、SSE 与侧栏组合
```

- `ownership/` 和 `conversation/` SHALL 依赖消费方 Protocol，不导入 FastAPI、psycopg、具体 JWT/密码库或浏览器概念。
- `conversation/` 只接收已解析 actor/owner，不解析 Cookie 或密码；`agent/` 不拥有用户/session 业务事实。
- `infra/security/` 与 `infra/platform/` 只实现端口；`interfaces/http/` 只映射协议；注册、删除、TTL 和提交顺序不得下沉到 adapter/route。
- 前端不得新增全局 auth 平台、管理后台、RBAC、组织、未来模块共享层或空路由。Build 可因真实内聚性合并/拆分文件，但必须保持上述方向。

## 16. 验收基线

实现 SHALL 使用无网络、无真实凭据的 fake model/clock、内存 adapter 和隔离 PostgreSQL 证明：

- guest/user/temporary guest 的 bootstrap、JWT 校验、refresh 轮换/并发宽限、撤销、过期、Origin/CORS 与 owner active 回查正确；
- 注册、登录、改密、退出和注销覆盖用户名规范化、密码边界、枚举防护、session 撤销与稳定错误；
- 跨 owner 的 thread、history、run cancel、rename/delete 不泄露存在性；
- account 跨两个浏览器 context 恢复 committed history/title，失败/取消/partial 不跨设备；
- 匿名 7 天期限只由成功提交推进，小时 sweep、active run 竞态、限额和孤儿 owner/session 行为正确；
- pending/checkpoint/commit 每个故障点都不产生用户可见成功；取消与断流不新增 checkpoint，重启或请求前的真实修复会清除旧 checkpoint 链并与最近五个 committed turn 一致；
- v3→v4 删除全部旧业务 thread 和孤儿 checkpoint，失败不记 v4，重试幂等且不访问 LangGraph 物理表；
- 单 thread 和账号删除中断可恢复，删除对象始终不可访问；
- temporary 模式匿名可用、账号入口 modal 完整、休眠账号 Cookie 不被破坏、重启不迁移；
- Vue 正常、加载、空、离线、无权、401/404/409/429/503、删除、跨标签页退出/注销、移动抽屉、焦点与长文本布局通过浏览器验证，且不存在本机历史入口；
- M01--M03 的同步、SSE、取消、断开、线程隔离、最近五轮与显式 migration 回归保持通过。
