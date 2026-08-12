# Conversation Persistence 完整目标规格

## 1. 能力定位

M03 `conversation-persistence` 为 VenAgent 提供 PostgreSQL 持久 thread、显式 schema migration、服务重启恢复和官方 LangGraph persistent checkpointer。M04 在此基础上正式扩展 owner、业务 turn、标题、账号跨设备历史与匿名保留；本规格描述 M04 完成后的完整持久化边界。

VenAgent SHALL NOT 提供浏览器旧会话导入、自制 checkpoint 表、业务 snapshot 模拟 LangGraph checkpoint、启动路径无版本 DDL、会话搜索/文件夹/归档/分叉/分享/导入导出或运行断线续传。

## 2. 持久事实源

- `conversation_threads` SHALL 保存 thread 的 owner、生命周期、标题、匿名成功时间、业务/checkpoint 版本与创建/更新时间。
- `conversation_turns` SHALL 保存完整成功的 user/assistant 业务轮次，并作为跨设备历史与 checkpoint 修复的事实源。
- 官方 LangGraph checkpointer SHALL 独立保存最近五个 committed turn 的图执行投影、writes 与 blobs。
- 浏览器 localStorage SHALL 只保存可见记录、账号缓存、草稿、失败/取消/partial 与 `local_only` 状态；不得替代服务端业务 history 或 checkpoint。
- VenAgent SHALL NOT 直接查询、修改或建立外键到官方 checkpointer 的物理表；只使用公开 state/checkpointer API。

## 3. 成功、提交与最近五轮

- 只有完整 user/assistant 对可成为 committed turn。模型异常、取消、断开、pending user、partial assistant、active run、取消信号与 SSE 事件不得成为业务历史。
- conversation SHALL 在模型调用前按 `(thread_id, client_message_id)` 执行幂等预检；committed 命中直接按同步/SSE 原协议重放，pending 命中先修复，同 ID 不同输入冲突。
- 模型完整成功后，conversation 提交协调器 SHALL 先插入不可见 pending turn，再更新最近五轮 checkpoint 投影，最后在业务事务中 committed turn并更新 thread 元数据；只有版本一致后才返回同步成功或 SSE `completed`。
- `(thread_id, client_message_id)` SHALL 幂等，重复提交不得形成第二个 turn 或第二次模型调用；同 ID 不同输入 SHALL 冲突。
- `history_version` 与 `checkpoint_version` SHALL 表达业务 history 和运行投影的一致性。pending 或版本不一致时，系统 SHALL 从 committed turns 重建 checkpoint 并清理未决 pending；修复失败 SHALL fail closed。
- 模型上下文 SHALL 最多包含最近五个完整 committed turn，按时间正序、以完整对裁剪。

## 4. Owner 与资源隔离

- 每个 durable thread SHALL 有非空 `owner_id`，关联 `guest|user` owner。thread、turn 与 run 的服务端访问必须按当前 actor/owner 过滤。
- `thread_id`、`run_id` 与 `owner_id` 不得混用。格式正确的其他 owner ID 与不存在/过期资源 SHALL 使用相同安全 404 语义。
- user thread 不自动过期；guest thread 依据 `last_successful_at + 7 days` 或无成功时 `created_at + 7 days` 独立过期。
- browser guest Cookie 丢失或账号登录后不得通过 thread ID 重新绑定旧 guest thread。

## 5. Thread 生命周期、历史与标题

- thread lifecycle SHALL 至少支持 `active|deleting`；v3 升级兼容代码 MAY 识别旧 `importing` 但不得重新暴露导入能力。
- `active` thread 可读取/运行；`deleting` thread 不得创建新运行并使用稳定冲突或不可见语义。
- `POST /api/threads` 成功前，权威 thread 元数据 SHALL 已建立并绑定当前 owner。
- owner thread 列表 SHALL 使用 `(owner_id, updated_at DESC, thread_id)` 游标分页；thread 详情只返回 committed turns。
- 新 thread 标题为“新对话”；首个成功 turn 可生成自动标题，手动标题永久压过自动标题。标题规则与 owner-scoped rename 由 M04 规格定义。
- server thread 已不存在时，浏览器记录 SHALL 变为 `local_only` 只读；不得自动删除、上传、恢复、认领或重新绑定。

## 6. 运行、重启与取消

- 服务重启后，durable thread SHALL 保持原 `thread_id`，并从 committed history/checkpoint 继续最近五轮上下文。
- 重启 SHALL 清空进程内 busy、active run 和取消 registry；旧 `run_id` 继续返回 `run_not_found`，运行不得自动继续、重放或补交。
- 同 thread 单活跃运行、不同 thread 并发、目标取消、断开取消和唯一 SSE 终态 SHALL 保持 M01/M02 契约。
- owner 注销 SHALL 请求取消该 owner 的 active run；物理删除只能在运行收口后继续。普通删除 active thread 保持 HTTP 409 `thread_active`。
- M04 只支持单 API 进程；多 worker、多实例锁、跨实例取消和分布式清理不属于本阶段。

## 7. 删除与清理

- 单 thread 删除、guest 到期、账号注销和 migration 清理 SHALL 先使资源不可访问，再调用公开 `delete_thread(thread_id)` 清理 checkpoint，最后删除 turns/thread/owner 业务记录。
- 数据库级联 SHALL 只用于业务表完整性，不得代替 checkpoint 清理。
- 删除 SHALL 可安全重试。部分失败不得返回完整成功或恢复资源可访问性；启动恢复/维护任务 SHALL 收敛 `deleting` 残留。
- guest sweeper SHALL 每小时执行并避开 active run；成功完成可续期，失败/取消且已过期则下一轮删除。
- 账号注销 SHALL 保持 owner `deleting`，直至全部 session、thread、turn、checkpoint、user 与 owner 主数据清理完成。

## 8. Schema 与 v4 Migration

- VenAgent schema SHALL 有连续明确版本，并拒绝未知新版本、非连续历史或不满足约束的状态。
- v4 SHALL 包含 `owners`、`users`、`auth_sessions`、`guest_sessions`、扩展后的 `conversation_threads` 与 `conversation_turns`；字段、约束和索引以 M04 规格为权威。
- 显式 v3→v4 migration SHALL 取得独占维护锁，枚举全部 v3 thread，并使用公开 checkpointer `list` 发现孤儿 checkpoint thread。
- 迁移 SHALL 对全部旧 ID 调用公开 `delete_thread`。只有清理成功后才创建/修改 v4 业务 schema并记录版本 4；失败不得记录 v4，重试必须幂等。
- v3 的所有无 owner server thread/checkpoint SHALL 永久删除，不迁移、不认领、不从 checkpoint 反推 business history；旧浏览器记录仅转为本地只读。
- 普通应用启动 SHALL NOT 自动执行 DDL，只校验 VenAgent v4 与官方 checkpointer schema 兼容。

## 9. Durable 与 Temporary 模式

- PostgreSQL 未配置、连接失败、v4 schema 不可用或持久认证配置不安全时，启动 SHALL 固定选择 temporary memory 模式；基础匿名聊天可用，但数据重启丢失且账号模块不可用。
- temporary 模式 SHALL 在内存实现同一 owner-scoped conversation、历史、标题、SSE、取消和删除接口，但不得迁移到 durable 模式。
- durable 模式运行中数据库故障 SHALL NOT 热切到内存；请求失败并由前端明确呈现。
- `GET /health` SHALL 保持顶层 `status: ok`，并公开 mode、PostgreSQL、anonymous chat、account identity、conversation persistence 与稳定 reason code；不得泄露连接串、凭据或原始异常。
- M03/M04 SHALL NOT 新增没有真实依赖判断的 `/readyz`。

## 10. Web 记录与兼容性

- Web SHALL 区分 server-backed、账号 cache、本机失败/partial 与匿名 `local_only`；只有稳定 `thread_not_found` 可把 server-backed 记录降为 `local_only`。
- 普通网络、模型、取消、429、409 或 503 不得删除/降级本地记录。
- `local_only` 已有消息可查看且用户可删除，但发送、重试、取消、上传、恢复和认领 SHALL 禁用。
- 登录时匿名本机历史隐藏但不迁移；退出后重新显示。账号历史由服务端 committed turns 权威恢复。
- M01 同步 API、M02 SSE 事件/取消和现有线程错误语义 SHALL 保持；M04 只增加 Bearer actor、`client_message_id`、历史/标题 API 和 owner 校验。
- 后端 SHALL NOT 提供旧浏览器导入 API；OpenAPI、健康状态和前端均不得重新暴露该能力。

## 11. 相邻模块边界

- M01 定义 thread、有限上下文与隔离；M02 定义 `run_id`、SSE、取消和断开；M03/M04 共同定义持久业务历史、checkpoint 投影、owner 与生命周期。
- M05 长期记忆、M06 工具执行、M07 编排恢复、M08 RAG 和 M09 多实例治理不得写入 conversation/checkpoint 表作为捷径。
- checkpointer 是运行投影，不是用户资料、长期记忆、任务业务事实、文档库、审计库或 server history API。

## 12. 验收基线

实现 SHALL 使用 fake model/clock、内存 adapter 和隔离 PostgreSQL 证明：

- committed history 与最近五轮 checkpoint 在同步、SSE、重启和跨浏览器下保持一致；
- 模型失败、取消、断开及 pending/checkpoint/commit 故障均不形成可见成功或幽灵轮次；
- owner/thread/run 隔离、幂等消息、标题、分页、guest TTL 与 user 永久保留符合契约；
- v3→v4 删除全部旧 thread 与孤儿 checkpoint，失败不记 v4，重试幂等且不接触 LangGraph 物理表；
- thread/账号删除的 checkpoint-first 顺序、中断恢复和不可访问状态正确；
- temporary 模式准确表达重启丢失和账号不可用，durable 运行故障不热切；
- `local_only` 在刷新后仍只读、可人工删除且不可上传/恢复；
- M01--M03 的 API、SSE、取消、线程隔离、显式 migration 和 Web 回归继续通过。
