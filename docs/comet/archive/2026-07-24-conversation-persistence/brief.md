# Outcome

完成 M03 `conversation-persistence` 的独立审计、取舍、完整目标规格、实现和验收，使 M01/M02 已完整提交的对话上下文可跨服务重启恢复，同时保持线程隔离、失败不提交、最近 5 个成功轮次和断开即取消等既有契约。

# Scope

- 为权威线程存在性提供持久化事实源，服务重启后已存在的 `thread_id` 仍可用于同步和流式聊天。
- 用 LangGraph 公开 checkpointer 边界持久化 committed graph state；只恢复完整成功轮次。
- 分离线程业务元数据与 LangGraph checkpoint，不以聊天表、自制 snapshot 或浏览器记录模拟框架 checkpoint。
- 定义数据库 schema 建立/升级、启动检查、明确删除和数据库清理的一致性边界。
- 更新最小配置、健康状态、测试和 Web UI 提示，使持久化成功、不可用和旧本地记录状态可区分。
- 提供根级最小 Docker Compose PostgreSQL 服务；应用仍可在宿主机运行并连接容器数据库。
- 提供受限的 M01 localStorage 旧会话迁移入口，把经用户确认的最近 5 个合格轮次导入为新的 durable thread；该入口不是通用备份导入或服务端会话库。
- 保持同步 API、SSE、目标取消和现有 Web UI 会话切换的兼容行为。

# Non-goals

- 不实现服务端会话列表、完整历史读取、标题/文件夹、归档、分叉、通用备份导入导出或跨设备会话库；M03A 已被路线明确 `drop`。M03 只允许一次受限的现有 `venagent.conversations.v1` 本地记录迁移，不形成可扩展会话库接口。
- 不持久化 active run、partial token、SSE 事件或终态，不实现断线续传、事件回放、后台继续或可靠运行恢复；这些不属于 M03，复杂恢复属于 M15。
- 不引入 `owner_id`、登录、JWT、跨用户授权或按用户保留策略；这些属于 M04。
- 不实现长期语义记忆、偏好、RAG、工具、计划或子 Agent 数据。
- 不复制 AGI-saber 按 `user_id` 混合加载 chat history 的实现，也不迁移其源码或数据库。

# Acceptance examples

- 创建线程并完成若干同步或流式成功轮次，关闭并重新创建应用服务后，用同一 `thread_id` 继续提问，模型输入只包含此前最近 5 个完整成功轮次且顺序正确。
- 取消、模型错误或异常断流产生的 pending user、partial assistant 和 active run 不写入 durable state；重启后下一轮看不到这些半轮。
- 两个线程跨重启后仍保持隔离；删除线程后，其业务元数据和全部 checkpoint 数据均被清除，后续请求返回 `thread_not_found`，重复删除仍为 HTTP 204。
- 持久化配置或 schema 不可用时，服务行为遵循已确认的启动/降级契约，不把内存运行伪装成 durable success。
- PostgreSQL 未配置或启动连接不可用时，服务以受支持的进程内模式启动；终端和 `/health` 明确显示聊天可用、持久化不可用，而不是把该模式表达为异常事故。
- schema 从受支持的旧版本升级到当前版本后，现有线程仍可恢复；失败升级不留下被应用误认成当前版本的半迁移状态。
- 对已失效的 M01 本地会话执行迁移时，服务端只创建一个新的权威 durable `thread_id`；重复提交同一迁移不会创建重复线程，失败不会留下可使用的半导入线程。
- M01 同步 API 和 M02 SSE/取消回归继续通过，且重启不会恢复 active run 或允许旧 `run_id` 取消任何运行。

# Constraints and invariants

- `thread_id` 继续只是对话隔离键，不是身份或授权凭据；M04 前只适用于单用户或受信环境。
- 线程业务元数据与 LangGraph checkpoint 分别建模；浏览器 localStorage 仍只是完整可见记录，不是后端事实源。
- 原生 M01/M02 运行仍只有完整 `completed` 轮次可持久化；模型失败、取消和断开不得自动提交半轮。唯一例外是 Q3 受限旧会话迁移中由用户显式选中的 legacy partial，且必须记录独立 provenance，不得伪装成原生 completed。
- 每个线程最多保留最近 5 个模型可见轮次，裁剪按完整 user/assistant 对进行；原生轮次必须 completed，用户选中的 legacy cancelled partial 作为带 provenance 的迁移例外计入同一窗口。
- 同线程单活跃运行、不同线程可并发、active thread 不可删除的 M01/M02 契约保持不变；busy 与 active run 仍是进程内状态，重启后清空。
- `run_id` 仍只在当前进程 active registry 中有效；M03 不提供 run status 或恢复 API。
- 外部基础设施失败不得伪装成成功；测试必须提供无网络、无真实凭据路径。
- 数据库连接串和凭据不得返回客户端、写入日志或 Comet 产物。
- 官方 LangGraph PostgreSQL checkpointer 的物理表属于框架私有实现；VenAgent 不修改其列、建立业务外键或直接查询内部表。
- 启动时选定的 PostgreSQL durable 或 memory degraded 模式在该进程生命周期内固定，避免运行中切换产生两份线程事实源。
- 旧会话迁移只在 PostgreSQL durable 模式可用；memory degraded 模式不得把本地记录伪装成已持久化。
- 迁移 SHALL 使用稳定 import key 幂等处理，并以 `importing` 生命周期或等价可恢复状态保证线程元数据与 checkpoint 全有或全无；独立 `conversation_imports` 映射 SHALL 绑定 import key、payload hash 与新 `thread_id`。服务端校验 schema 版本、角色、状态、顺序、轮数、消息非空与大小边界，并记录安全的 legacy-browser provenance。

# Decisions

- M03 使用独立 capability ID `conversation-persistence`，整体取舍为 `replace`：保留持久对话与重启恢复目标，拒绝 AGI-saber 的按用户共享 STM、手写 chat-history 预热和应用启动期散落 DDL。
- 重启恢复只覆盖已完整提交的对话上下文，不恢复 M02 active run、partial token、SSE 事件或取消信号。
- 线程元数据与官方 LangGraph checkpointer 保持不同存储职责；显式删除必须清理二者。
- M03 不恢复已被路线 `drop` 的 M03A 会话库能力，也不提前实现 M04/M15。
- M03 首个交付只支持 PostgreSQL 持久化后端，并提供只包含 PostgreSQL、持久 volume 与 healthcheck 的根级 Docker Compose 配置；不要求 Windows 本机安装 PostgreSQL。
- VenAgent 自有 `conversation_threads` 只保存权威 `thread_id`、`importing/active/deleting` 生命周期和创建、更新时间及删除请求时间；不保存消息、owner、标题、run 或通用 metadata。删除先标记 `deleting`，再调用官方 checkpointer 清理，成功后删除元数据；清理中的聊天返回 HTTP 409 `thread_deleting`。
- 官方 PostgreSQL checkpointer 只通过公开 API 和官方初始化/升级入口使用；业务 schema 与框架 schema 独立管理，VenAgent 不建立第二份 `chat_history` 事实源。
- PostgreSQL 未配置、启动连接失败或启动 schema 检查不可用时，应用以受支持的 memory degraded 模式启动，聊天与进程内上下文保持可用，但不具备跨重启持久化。
- 降级是预期运行模式：终端同时输出稳定结构化字段和对应的中文自然语言说明，不使用事故化措辞，不输出 DSN、凭据或原始数据库错误。中文说明须明确当前是否可跨重启恢复；`/health` 保持 HTTP 200 与顶层 `status: ok`，并分别公开运行模式、PostgreSQL 状态和能力状态，至少表明 chat `available`、conversation persistence `unavailable`。
- AGI-saber 无条件返回 `healthz/readyz=ok` 的行为不采用；M03 不新增无真实依赖判断的就绪探针。已以 PostgreSQL 模式启动后发生运行中故障时不自动切换内存，相关持久写失败关闭。
- Q3 选择 B：允许把 M03 上线前 `venagent.conversations.v1` localStorage 旧会话的最近 5 个合格完整轮次导入为新的 durable thread；不得复用失效旧 `thread_id`，也不得把该能力扩展成 M03A 会话库。
- Q4 选择 B：VenAgent 自有 schema 与官方 checkpointer schema 均通过显式迁移/初始化命令建立或升级；应用普通启动只校验兼容性，缺失或不兼容时按 Q2 进入 memory degraded，不在启动路径静默执行 DDL。
- Q5 采用细化规则：`sent/sent` 非空完整成功对可导入；带非空 assistant 文本的明确 `cancelled` 轮次可由用户逐轮勾选；空 partial、孤立消息和状态不明记录只保留显示。现有 v1 `failed` 无法区分模型错误、连接失败和页面重载遗留状态，其处理留给 Q9。
- Q6 选择 A：只有旧线程实际返回 `thread_not_found` 后才显示逐会话导入确认，不自动扫描或批量导入其他本地会话。
- Q7 选择 A：导入成功后在原本地会话上原子替换为新的权威 `thread_id` 并原位继续；完整可见记录仍保留，但明确说明模型只接收本次选中的最近 5 轮。
- Q8 选择 A：导入后保持原 user/assistant 角色；完整成功对记录 `legacy_browser_import` provenance，用户选中的 partial 另记录 `legacy_browser_partial` provenance。
- Q9 选择 A：现有 v1 assistant `failed` partial 一律排除导入，只保留浏览器显示；不根据文本内容猜测它来自模型错误、连接失败还是页面重载遗留状态。
- 用户已明确确认本 brief 与 `conversation-persistence` 完整目标规格所定义的目标、范围、关键决定、验收标准和非目标，批准进入 Build。

# Open questions

无。所有已识别用户可见分支均已确认。

# Verification expectations

- 使用临时数据库和可控假模型覆盖创建、成功提交、重启恢复、窗口裁剪、线程隔离、显式删除与重复删除。
- 覆盖同步成功、流式成功、取消、模型错误和异常断流，证明只有 completed 轮次进入 durable checkpoint。
- 覆盖数据库不可用、只读、损坏/未知 schema 版本与迁移失败，验证不会静默降级或泄露连接信息。
- 覆盖并发线程和同线程互斥回归，并证明重启清除 busy、active run 与旧 `run_id`。
- 覆盖旧会话导入的资格过滤、最多 5 轮、大小限制、稳定 import key、并发重试、网络响应丢失、半导入恢复、provenance 和 degraded 模式拒绝。
- 运行现有完整 pytest、Python 编译、Web 脚本语法检查和 Comet 有界文本检查；真实外部数据库或浏览器检查如未运行须如实记录。
