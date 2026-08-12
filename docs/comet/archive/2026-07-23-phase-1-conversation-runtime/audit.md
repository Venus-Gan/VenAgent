# M01 conversation-context 专项审计

## 审计结论

M01 的产品目标应当保留：VenAgent 需要让同一对话看到有限的已完成历史，并让不同对话互不串线。但 AGI-saber 的核心实现不能沿用。旧项目的 Web UI 会话 ID 只存在于浏览器，聊天请求没有携带该 ID；后端短期历史按 `userID` 分桶。因此旧项目实现的是“每个用户一份共享历史”，不是“每个会话一份上下文”。

用户已确认把 M01 整体取舍定为 `replace`：保留多轮对话、固定窗口和会话列表的产品意图，用 LangGraph `thread_id`、`InMemorySaver` 和明确的线程 API 重做隔离边界。SSE、token 流、取消和断线行为属于 M02，不进入 M01。

## VenAgent 当前事实

- `venagent/agent_loop.py` 编译 `StateGraph` 时没有 checkpointer；`run(message)` 每次只提交当前 `HumanMessage`，所以当前是单轮调用。
- `venagent/api.py` 的 `POST /api/chat` 请求只有 `message`，响应只有 `answer`，没有线程身份或线程生命周期 API。
- `venagent/web/index.html` 只有当前页面内的消息 DOM；没有会话 ID、会话列表、localStorage 恢复或后端清理动作。
- `tests/test_agent_loop.py` 和 `tests/test_api.py` 只验证单轮成功、空输入和页面入口；没有多轮、隔离、窗口或线程删除测试。

因此 M01 是在当前最小 Agent Loop 上增加第一层有状态能力，不需要兼容 VenAgent 既有会话数据。

## AGI-saber 直接证据

### 浏览器会话没有进入后端

- `web/src/stores/sessions.js` 使用 `Date.now().toString()` 生成本地 session ID，把最多 5 个会话和消息写入 `localStorage`。
- `web/src/stores/chat.js` 虽然读取 `sess.currentId` 来更新当前 UI 会话，但发给 `/api/chat/stream` 和 `/api/chat` 的请求体只有 `message`、`use_rag` 和 `explicit`，没有 session ID。
- 删除会话只过滤浏览器数组并保存 localStorage，没有通知后端删除对应上下文。

结果是：UI 看起来有多个会话，但切换会话不会切换模型上下文。

### 后端按用户而不是按会话分桶

- `internal/application/chat/mem_stack.go` 的短期历史容器是 `map[string]*shortterm.ShortTerm`，键为 `userID`；首次访问还会按同一 `userID` 从 PostgreSQL 预热。
- `internal/infrastructure/persistence/chathistory/chathistory.go` 的读写条件只有 `user_id`，数据模型没有 `thread_id` 或 conversation ID。
- `internal/application/chat/ctx_builder.go` 通过 `STM(userID)` 组装历史。
- `internal/domain/memory/shortterm/shortterm.go` 按 `MaxTurns * 2` 截断消息，固定轮数思想本身可保留。

结果是：同一账号打开的多个 UI 会话共享同一个 STM 与持久历史；只有不同用户之间实现了隔离。

### 失败轮次可能污染历史

- `internal/application/chat/runtime_process.go` 在模型执行前就把 user 消息写入 STM 和 PostgreSQL，模型结束后才写 assistant。
- 模型失败、取消或进程异常可能留下只有 user 的半轮；后续上下文会读到这条不完整历史。

M01 必须把“待处理输入”和“已完成历史”分开，只有完整成功的 user/assistant 对才进入模型可见的已提交上下文。

## 子能力取舍建议

| 子能力 | 建议 | 理由与边界 |
| --- | --- | --- |
| 多轮对话目标 | `adopt` | 同一会话需要看到最近若干完整轮次。 |
| 固定轮数窗口 | `adopt` | 简单、可测试，可防止提示上下文无限增长；具体轮数待模块方向确认后决定。 |
| 浏览器会话列表方向 | `partial` | 保留新建、切换、删除和本地标题；不沿用时间戳 ID，也不把浏览器历史当作后端权威。 |
| `userID` 短期历史桶 | `replace` | 改为 LangGraph `thread_id` 隔离；身份与所有权留给 M04。 |
| 自制 `ShortTerm` 容器 | `replace` | 改用 `StateGraph.compile(checkpointer=InMemorySaver())` 和有界 committed messages。 |
| PostgreSQL 历史预热 | `defer` | 属于 M03 conversation-persistence，M01 明确只在进程内存活。 |
| 偏好、长期记忆注入 | `drop`（对 M01） | 分别由 M05、M07/M08 审计，不混入对话上下文。 |
| SSE、取消、断线恢复 | `defer` | 属于 M02 streaming-run-lifecycle。 |
| 自动过期/容量淘汰 | `defer` | M01 先提供显式删除和进程重启清空；是否需要自动策略由后续生命周期证据决定。 |

## 推荐的 M01 边界

如果用户批准整体 `replace`，M01 后续目标规格应只覆盖：

1. 服务端生成并返回不透明 `thread_id`，聊天请求显式携带它。
2. LangGraph 以 `configurable.thread_id` 选择 `InMemorySaver` 中的线程状态。
3. 模型只读取同线程最近 N 个完整成功轮次；失败调用不提交半轮。
4. 不同线程并发不串状态；同线程重入必须有确定行为。
5. 提供新建和显式删除线程的最小 API；删除同时清理线程元数据与 checkpointer 数据。
6. Web UI 最小增加新建、切换、删除和本地会话展示，每次聊天发送当前 `thread_id`。
7. 明确提示进程重启会让后端线程失效；不承诺跨进程恢复。

## M01 与相邻模块的边界

- M02 才定义 SSE 事件、token streaming、目标运行取消、客户端断线和流中错误。
- M03 才定义持久化 checkpointer、服务重启恢复、迁移和数据库清理。
- M04 才定义 `owner_id`、鉴权、跨用户授权和数据保留策略。M01 的 `thread_id` 不是授权凭据，因此在 M04 完成前只适合单用户或受信环境。
- M05/M07/M08 才定义跨线程偏好、长期事实和记忆治理；M01 历史不得承担这些职责。

## 风险与验证重点

- 仅给图加 `InMemorySaver` 并把 `HumanMessage` 直接作为图输入，失败时可能留下输入 checkpoint；实现必须用状态结构或执行边界保证失败输入不会成为 committed history。
- `InMemorySaver` 只适合单进程；多 worker 会产生不一致的线程视图，M01 部署约束必须明确单进程。
- 浏览器本地消息与后端模型上下文是两个副本；服务重启后必须显式处理旧引用，不能静默假装历史仍然存在。
- 后续实现测试至少覆盖同线程多轮、跨线程隔离、窗口边界、模型失败不提交、未知线程、删除目标线程以及删除不影响其他线程。

## 主流桌面 Agent 会话模式参考

本轮额外核对了能够访问的官方桌面产品文档：

- VS Code Agent/Chat Sessions 把每次会话建模为拥有独立 context window 的 session，并提供会话列表、归档、永久删除、分叉以及保存/导出能力。会话记录是用户可管理的桌面资产，不等于当前模型上下文窗口。
- LM Studio 支持创建多个 conversation threads、文件夹、复制会话和分屏，并明确说明会话以 JSON 存储在本地文件系统中。它同样把完整可见记录与模型是否“学习/记住”这些记录区分开。
- LangGraph 官方文档把 State 定义为应用当前快照的共享数据结构；checkpointer 按 `thread_id` 保存 graph state，用于线程内短期记忆。Store 则用于跨线程长期事实与偏好。

对 M01 的可采用结论：

1. 浏览器侧可以保存完整可见会话、标题、排序和 `thread_id`，形成桌面式会话资产。
2. LangGraph State 只保存运行所需的最近 5 个完整成功轮次，不因为 UI 能显示更早记录就把全部记录重新注入模型。
3. 服务重启后，本地记录仍可阅读，但对应的内存 thread 已失效；不得把“记录仍可见”表现成“模型仍记得”。
4. M01 不需要复制归档、文件夹、分叉、导出等完整桌面管理能力，只为未来保留可演进的数据结构。

推荐排期是在 M03 `conversation-persistence` 之后、M04 `ownership-lifecycle` 之前增加待单独批准的 `M03A conversation-library`：

- M03 先建立可持久恢复的会话与 checkpoint 事实源；
- M03A 再实现归档、文件夹、分叉和导出，避免基于 localStorage 做一次临时版本后重新迁移；
- M04 后续为这些会话资产增加 owner 与授权边界。

这只是审计建议，尚未修改已归档路线。新增模块、最终编号和子能力取舍必须通过独立路线修订 change 取得批准。

官方资料访问限制：OpenAI Help Center 在本环境持续超时/403，Cursor 旧文档路径统一重定向到文档首页，因此未把无法直接复核的产品细节写成 M01 事实。

## LangGraph State 澄清

M01 必须创建明确的 LangGraph State；“不建立通用 Agent 状态机”不表示不创建 State。

建议的最小图状态只表达图节点需要共享和 checkpoint 的数据：

- `messages`：最近 5 个完整成功的 user/assistant 对；
- `pending_user`：本次待处理输入，用于确保失败输入不进入 committed `messages`。

`thread_id` 通过 LangGraph config 传递，不放进 State。`idle/busy` 是服务层并发元数据，不放进 State。未来工具步骤、计划、审批、产物和子 Agent 字段由对应模块在有真实需求时扩展 State，不在 M01 预建通用枚举状态机。

## 整体状态决定

已确认：`replace`。

理由：旧项目的产品目标有价值，但它以 `userID` 代替会话身份，恰好违反 M01 的核心隔离要求；只有外围思想可部分采用。`adopt` 会错误表示主要方法得到保留，`partial` 又不足以表达核心存储与隔离机制已被替换。
