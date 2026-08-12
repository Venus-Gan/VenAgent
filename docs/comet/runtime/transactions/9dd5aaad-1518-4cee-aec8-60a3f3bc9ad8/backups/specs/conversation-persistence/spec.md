# Conversation Persistence 完整目标规格

## 1. 模块取舍

M03 `conversation-persistence` 的整体状态为 `replace`。

VenAgent SHALL 保留持久对话、服务重启恢复、schema 迁移和明确清理的产品目标，但 SHALL NOT 沿用 AGI-saber 按 `user_id` 共享聊天历史、自制短期记忆预热、用业务 snapshot 模拟框架 checkpoint 或散落在应用启动路径中的无版本 DDL。

## 2. 能力目标

`conversation-persistence` SHALL 在 M01/M02 契约上建立 durable thread metadata 与官方 LangGraph persistent checkpointer，使最近 5 个模型可见轮次可跨服务重启继续使用。原生轮次仍只接受 completed；用户确认的受限 legacy cancelled partial 是带 provenance 的唯一迁移例外。

M03 首个交付 SHALL 使用 PostgreSQL 持久化，并提供根级最小 Docker Compose 服务，使本机无需直接安装 PostgreSQL。VenAgent 与官方 checkpointer schema SHALL 由显式迁移/初始化命令建立和升级，普通启动只校验兼容性。M03 还 SHALL 提供现有 `venagent.conversations.v1` localStorage 旧会话到新 durable thread 的受限迁移，并遵循第 8 节已确认的资格、确认、UI 结果与角色信任语义。

## 3. 持久状态边界

- 线程业务元数据 SHALL 记录权威 `thread_id` 及持久生命周期事实；LangGraph checkpointer SHALL 独立保存 graph state、checkpoint writes 与 blobs。
- 业务元数据与 checkpoint SHALL 分别建模，不得以浏览器 localStorage、chat history 表或自制 snapshot 代替官方 checkpointer。
- graph state SHALL 继续只包含 committed `messages` 与当前图执行所需字段；`thread_id` SHALL 继续通过 LangGraph config 传递。
- 原生运行只有完整成功且形成 M01 同步成功或 M02 `completed` 终态的 user/assistant 对才可进入 durable state。
- 模型异常、取消、断开、pending user、partial assistant、active run、取消信号和 SSE 事件 SHALL NOT 自动提交或恢复。第 8 节受限迁移中由用户逐轮确认的 legacy partial 是唯一例外，并必须带独立 provenance。
- 每个线程 SHALL 只保留最近 5 个完整成功轮次，按时间正序、以完整对为单位裁剪。
- VenAgent SHALL NOT 修改、扩展、直接查询官方 checkpointer 的物理表，也不得建立指向其内部表的业务外键。
- 后续 graph state、节点、边、子图和 interrupt 通过 LangGraph 公开 State/checkpointer 契约扩展；需要查询和治理的业务对象 SHALL 使用独立 VenAgent 表，不塞入框架私有 schema。

## 4. VenAgent 线程元数据

- VenAgent SHALL 自有 `conversation_threads` 表，至少包含权威 UUID `thread_id`、`importing/active/deleting` 生命周期、`created_at`、`updated_at` 与可空 `delete_requested_at`。
- `conversation_threads` SHALL NOT 保存消息正文、checkpoint blob、`owner_id`、标题、文件夹、`run_id`、消息计数或通用 `metadata` JSONB。
- VenAgent SHALL 自有独立 `conversation_imports` 幂等映射，至少绑定稳定 import key、规范 payload hash、新 `thread_id`、迁移状态和时间戳；业务表不得引用官方 checkpointer 内部表。
- `active` 线程可创建运行；`deleting` 线程不得创建新同步或流式运行，并 SHALL 返回 HTTP 409 与稳定 code `thread_deleting`。
- 删除 SHALL 先把元数据原子标记为 `deleting`，再通过官方 checkpointer API 删除该 `thread_id` 的 checkpoints、writes 与 blobs，最后删除线程元数据。
- 服务启动 SHALL 收敛遗留 `deleting` 记录；清理操作必须可重试，且不得在 checkpoint 未清理时先永久遗忘该线程。

## 5. 重启与运行生命周期

- 服务重启后，持久线程 SHALL 保持原 `thread_id`，同步与流式聊天可继续读取已提交上下文。
- 重启 SHALL 清空进程内 busy、active run 和取消 registry；任何旧 `run_id` SHALL 返回 M02 既有 `run_not_found`。
- 重启期间未形成成功终态的运行 SHALL 被视为未提交；M03 SHALL NOT 自动继续、重放或补交该轮。
- 同线程单活跃运行、不同线程并发、active thread 删除冲突和目标取消行为 SHALL 保持 M01/M02 契约。
- M03 SHALL NOT 新增 run status、resume、SSE replay 或 `Last-Event-ID` API。

## 6. 线程创建与删除

- `POST /api/threads` 成功前，权威线程元数据 SHALL 已持久化；创建失败不得返回一个只能在内存使用的 durable `thread_id`。
- 同步与流式聊天 SHALL 先依据持久线程事实判断存在性，再访问该线程 checkpoint；格式非法与未知线程继续使用既有安全错误。
- 删除空闲线程 SHALL 清理线程业务元数据及其全部 checkpoints、pending writes 与 blobs，且操作 SHALL 可安全重试。
- 删除完成后，同一 `thread_id` 的聊天 SHALL 返回 `thread_not_found`；重复删除 SHALL 继续幂等返回 HTTP 204。
- 删除部分失败不得让服务把只清理了一半的线程伪装成完整成功；实现 SHALL 提供可测试的失败关闭与残留收敛路径。
- 自动 TTL、按 owner 保留、归档和批量清理不属于 M03；数据保留生命周期属于 M04，M03 只提供显式线程删除和内部一致性清理。

## 7. Schema、降级与故障可见性

- 持久 schema SHALL 有明确版本，初始化和升级操作 SHALL 幂等，并拒绝未知的新版本或无法安全升级的状态。
- VenAgent SHALL 提供显式迁移命令管理自有 schema，并通过官方入口显式初始化或升级 checkpointer schema。普通应用启动 SHALL NOT 自动执行 DDL，只校验两类 schema 是否兼容。
- 迁移失败 SHALL NOT 把半迁移数据库标记为当前版本；应用不得在不兼容 schema 上继续写入。
- PostgreSQL 未配置、启动连接失败或启动 schema 检查不可用时，应用 SHALL 选择受支持的 memory degraded 模式；基础聊天与进程内上下文继续可用，但该进程创建的线程和消息不具备跨重启持久性。
- durable 或 degraded 模式 SHALL 在单个进程生命周期内固定。应用已经以 PostgreSQL durable 模式启动后发生数据库故障时，SHALL NOT 静默切换到内存并形成第二份状态；依赖持久写的操作应失败关闭。
- 启动终端 SHALL 同时输出稳定结构化字段和中文自然语言说明，显示已选择的模式、PostgreSQL 状态、稳定 reason code 以及对话能否跨重启恢复。中文说明至少覆盖以下语义：
  - durable：PostgreSQL 连接正常，对话可在服务重启后恢复；
  - `postgresql_not_configured`：未配置 PostgreSQL，当前使用进程内存，服务重启后对话上下文将失效；
  - `postgresql_unavailable` 或 `persistence_schema_unavailable`：PostgreSQL 或持久 schema 当前不可用，已使用进程内存启动，服务重启后对话上下文将失效。
- 中文说明 SHALL 使用稳定模板，不拼接连接串、凭据、原始数据库响应、内部栈或未经清理的异常文本。预期降级不得使用事故化措辞或装饰性符号。
- `GET /health` SHALL 保持 HTTP 200 与顶层 `status: ok`，表示进程仍可提供基础聊天；响应同时 SHALL 公开运行模式、基础设施和能力状态，至少可区分：
  - PostgreSQL `connected`、`disconnected` 或 `not_configured`；
  - chat `available`；
  - conversation persistence `available` 或 `unavailable`；
  - `postgresql_not_configured`、`postgresql_unavailable` 或 `persistence_schema_unavailable` 等稳定安全 reason code。
- M03 SHALL NOT 新增无条件返回成功的 `/readyz`。未来若增加 readiness，必须根据部署所需能力真实计算，不得照搬 AGI-saber 的无条件 `ok`。
- 测试 SHALL 能使用临时隔离数据库，不依赖真实凭据或外部网络。

## 8. 受限旧会话迁移

- M03 SHALL 允许把 `venagent.conversations.v1` 中经用户确认的最近 5 个合格轮次导入为新的 durable thread；旧失效 `thread_id` SHALL NOT 被复活或复用。
- 导入 API SHALL 使用独立 `POST /api/threads/import`，请求至少包含来源 schema version、稳定 import key、候选消息及用户选择的 partial 标识；成功响应至少包含新的权威 `thread_id` 与实际导入轮数。
- 迁移 SHALL 只在 PostgreSQL durable 模式可用；memory degraded 模式 SHALL 保留原本地记录并明确表示当前不能建立 durable 导入。
- 每次逻辑迁移 SHALL 带稳定、高熵 import key；相同 key 的并发、重试和响应丢失 SHALL 返回同一个结果，不得创建重复线程。
- 相同 import key 配合不同规范 payload hash SHALL 使用稳定 conflict 错误拒绝，不得覆盖既有映射或创建第二个线程。
- 服务端 SHALL 校验来源 schema version、消息角色、状态、顺序、完整轮次、非空文本、最多 5 轮和请求/单消息大小边界。未知字段不得获得额外行为，非法输入 SHALL 使用稳定安全错误拒绝。
- 导入创建的线程 SHALL 先处于不可聊天的 `importing` 或等价恢复状态；只有线程元数据和 checkpoint 均完整后才可原子暴露为 `active`。失败或重启后 SHALL 可重试收敛，不留下可用的半导入线程或无法追踪的孤儿 checkpoint。
- 非空 user `sent` + assistant `sent` 完整成功对 SHALL 具备导入资格。带非空 assistant 文本的明确 `cancelled` 轮次 MAY 由用户逐轮勾选；空 partial、孤立消息和状态不明记录 SHALL 只保留显示。
- 现有 v1 assistant `failed` 不含 failure kind，无法区分模型 error、连接失败和页面重载遗留 streaming；该类 partial SHALL 一律排除导入并只保留显示。
- 服务端 SHALL 先形成完整成功对与用户选中的 cancelled partial 候选集，按原时间顺序排序，再只保留最近 5 对；被选中的 cancelled partial 计为一个模型可见轮次。
- 完整成功对 SHALL 保存安全的 `legacy_browser_import` provenance；用户选中的 partial SHALL 保存 `legacy_browser_partial` provenance，供后续迁移、诊断和安全治理区分原生服务端轮次。
- 旧线程实际返回 `thread_not_found` 后，UI SHALL 针对当前会话显示导入确认；不得自动扫描、导入或上传其他本地会话。
- 导入成功后，UI SHALL 在原本地会话上原子替换新的权威 `thread_id` 并原位继续，保留全部可见记录，同时明确模型上下文只包含本次被选中的最近 5 轮。
- 导入 SHALL 保持被选中记录的原 user/assistant 角色；显式用户确认、严格验证和 provenance 不得被解释为服务端对原 assistant 内容真实性的背书。
- 该能力 SHALL 只接受当前 v1 本地会话迁移，不提供任意文件、备份、服务端历史、跨设备同步、归档、文件夹或分叉能力，也不恢复已 drop 的 M03A。
- 合格轮次、用户确认方式、导入后 UI 结果、角色处理和 failed partial 排除规则均已确认。

## 9. Web UI 与兼容性

- M01 同步 API、M02 SSE 事件和取消 API 的请求/成功结构 SHALL 保持兼容；M03 不新增服务端会话列表或历史读取 API。
- Web UI SHALL 继续把 localStorage 完整可见记录与后端模型上下文分层，不得把本地记录自动视为已持久化 checkpoint。
- Web UI SHALL 能根据健康状态说明当前是 durable 或仅当前进程有效的 memory 模式，不得把 degraded 模式表示为已持久化。
- 新建、切换、删除、completed、cancelled、error 和连接丢失状态 SHALL 保持 M02 行为；页面不得把一个线程的恢复结果写入另一个线程。
- M03A 已 drop 的标题、文件夹、归档、分叉、原生备份导入导出和会话资料引用 SHALL NOT 因 M03 持久化而恢复。

## 10. 相邻模块边界

- M01 继续定义线程身份、上下文隔离、最近 5 个成功轮次、同步 API 和基础 Web UI。
- M02 继续定义 `run_id`、SSE、token streaming、目标取消、断开和流中错误；M03 不改变其断开即取消契约。
- M04 定义 `owner_id`、认证授权、跨用户边界、保留期限和用户级数据生命周期。
- M07 定义可靠并行、幂等重试、长任务 checkpoint 恢复和复杂部分失败。

## 11. 验收基线

实现 SHALL 使用无网络、无真实凭据的可控模型和临时数据库证明：

- 已提交对话跨服务实例重建后可继续，且最多保留最近 5 个模型可见轮次；原生轮次必须 completed，迁移 partial 必须满足第 8 节例外；
- 不同线程跨重启后仍隔离，并发执行不串状态；
- 同步失败、流式错误、取消和异常断流均不持久化半轮；
- 重启清空 busy、active run 和旧取消句柄，不恢复或重放运行；
- 线程创建、未知、显式删除、重复删除和部分清理失败符合已确认契约；
- schema 初始化、受支持升级、未知版本和失败升级符合已确认契约；
- PostgreSQL 未配置、连接不可用和 schema 不可用时进入固定的 memory degraded 模式，终端通过结构化字段与中文自然语言说明、健康状态和 Web UI 均准确显示能力边界；
- durable 模式运行中数据库故障不静默切换内存，且错误不泄露数据库敏感信息；
- 旧浏览器记录导入符合用户确认的资格、逐轮 partial 选择、逐会话确认、原位继续和角色/provenance 语义；重复、并发、失败和重启恢复不产生重复线程或半导入可见状态；
- M01/M02 现有 API、SSE、取消与 Web UI 隔离回归继续通过。
