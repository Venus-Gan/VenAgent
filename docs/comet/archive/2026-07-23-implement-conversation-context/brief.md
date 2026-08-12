# Outcome

实现 canonical `conversation-context` 规格，使当前最小 Agent Loop 具备单进程、线程隔离、最多 5 个完整成功轮次的短期上下文，并让同步 API 与 Web UI 共用服务端签发的 `thread_id`。

# Scope

- 在 LangGraph State 中区分已提交 `messages` 和当前 `pending_user`，使用 `InMemorySaver` 与 `configurable.thread_id`。
- 增加轻量 `ConversationService`/`ThreadRegistry`，负责线程创建、存在性、同线程 busy 互斥、删除和 checkpointer 清理。
- 扩展同步 HTTP API：创建线程、携带线程聊天、删除线程，以及稳定安全的错误结构。
- 把单会话页面扩展为本地会话列表，支持新建、切换、删除、刷新恢复、失败重试和后端上下文失效只读状态。
- 增加离线可控模型的单元/API 测试，覆盖状态提交、窗口、隔离、并发和线程生命周期。

# Non-goals

- 不实现 SSE、token streaming、取消或断线恢复，这些属于 M02。
- 不实现进程重启后的后端恢复、数据库 checkpointer 或迁移，这些属于 M03。
- 不实现归档、文件夹、分叉、导出或未单独批准的 M03A。
- 不实现身份、所有权或授权，这些属于 M04；当前仍限单用户或受信环境。
- 不增加工具、计划、审批、运行事件、子 Agent 字段或通用 Agent 生命周期状态机。
- 不修改已废弃的 `final/` 运行时。

# Acceptance examples

- 创建两个线程后，线程 A 连续提问能够看到 A 的最近成功历史，线程 B 的模型输入不包含 A 的消息。
- 单线程成功超过 5 轮时，checkpoint 和下一次模型输入只包含最近 5 个完整 user/assistant 对且保持时间正序。
- 模型调用失败时，本次 user 输入和任何失败结果不进入已提交 State；重试仍从上一次成功历史开始。
- 同一线程已有同步请求时，第二次聊天返回 HTTP 409 `thread_busy`；不同线程可以并发。
- 活跃线程删除返回 HTTP 409 `thread_active`；空闲线程删除清理 registry 和 checkpointer；重复删除返回 204。
- 未注册线程聊天返回 HTTP 404 `thread_not_found`，不得静默创建新线程。
- 页面刷新保留完整可见记录；服务重启导致后端线程失效时，本地记录保留并变为只读，用户需新建对话。
- UI 切换会话期间，迟到响应只更新发起请求的会话；删除只在后端成功后移除本地记录。

# Constraints and invariants

- 以 `docs/comet/specs/conversation-context/spec.md` 为完整行为契约，本 change 只实现它，不改变长期规格。
- `thread_id` 使用服务端生成的高熵不透明 ID，只通过 LangGraph config 传递，不复制进 graph State，也不作为授权证明。
- 只在模型返回完整 `BaseMessage` 后提交完整 user/assistant 对；裁剪以完整轮次为单位。
- busy 元数据只属于服务层；不同线程不共享锁或状态。
- 客户端错误不得泄露内部异常、栈或凭据；技术错误 code 保持稳定，但本次不固定所有 UI 提示文字。
- 保留当前 OpenAI 兼容模型装配与无配置离线模型；不得读取或提交本机 `.env`。
- 保持实现轻量，优先在 `agent_loop.py`、新增 `conversation.py`、`api.py` 与单文件 Web UI 内完成。

# Decisions

- 用户已审批 M01 `replace` 方案及 canonical 规格，并明确要求执行下一步实现。
- 浏览器完整可见历史与后端 5 轮模型上下文是两个独立数据层。
- 线程必须显式创建；未知或重启失效线程不得自动恢复或重新绑定。
- M01 使用内存 checkpointer，重启后失效是已知且明确的阶段边界。

# Open questions

无阻塞问题。

# Verification expectations

- 使用项目 `.venv` 运行全部 `tests/`，不得访问真实模型网络。
- 覆盖图状态的多轮、5 轮裁剪、失败原子性和线程隔离。
- 覆盖 API 创建、聊天校验、稳定错误、同线程冲突、跨线程并发、删除和未知线程行为。
- 对 Web UI 做静态契约检查，并启动本地服务后用桌面与移动视口验证核心新建、切换、发送、删除和刷新流程。
- 记录未覆盖的真实第三方模型网络行为和 M01 明确的进程内限制。
