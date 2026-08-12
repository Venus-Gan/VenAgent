# Conversation Context 完整目标规格（拟议）

## 1. 模块取舍

M01 `conversation-context` 的整体状态为 `replace`。

VenAgent SHALL 保留同一对话的有限多轮上下文、不同对话隔离、会话 UI 和显式清理目标，但 SHALL NOT 沿用 AGI-saber 的浏览器时间戳 ID、按 `userID` 共享 STM、自制短期历史容器或模型调用前预写 user 历史。

## 2. 能力目标

`conversation-context` SHALL 为 VenAgent 提供单进程内的短期对话上下文：每个对话由独立 `thread_id` 标识，LangGraph 使用 `InMemorySaver` 保存有限的完整成功轮次，同步聊天 API 与 Web UI 使用相同线程身份。

`thread_id` SHALL 只作为对话隔离键，不表示用户身份或所有权，也不得作为授权边界。在 M04 完成前，该能力只适合单用户或受信运行环境。

## 3. LangGraph 状态边界

- M01 SHALL 定义明确且可扩展的 LangGraph State；State 是图节点共享数据和 checkpointer 快照的基座，不等于通用 Agent 生命周期状态机。
- 图 SHALL 使用 `StateGraph.compile(checkpointer=InMemorySaver())` 或锁定版本中的等价公开接口。
- 每次图调用 SHALL 显式传入 `configurable.thread_id`。
- State SHALL 至少区分 committed `messages` 与当前 `pending_user`。
- 模型完整成功后，当前 user/assistant 对才 SHALL 进入已提交历史。
- 模型异常时，失败输入和部分助手输出 SHALL NOT 成为后续模型可见历史。
- 线程 A 的消息、checkpoint、忙碌状态和删除动作 SHALL NOT 读写线程 B。
- 后端 SHALL 只保留最近 5 个完整成功轮次，并把更早轮次从模型输入与进程内线程状态中移除。
- 历史 SHALL 保持时间正序，裁剪 SHALL 以完整 user/assistant 对为单位。
- `thread_id` SHALL 通过 LangGraph config 传递而不是复制进 State。
- `idle/busy` SHALL 是 ConversationService/ThreadRegistry 的运行时并发元数据，不属于 graph state。
- 工具、计划、审批、产物、运行事件和子 Agent 字段 SHALL 只在对应模块获批后加入 State；M01 SHALL NOT 预建通用生命周期枚举。

## 4. 线程生命周期

- 客户端 SHALL 通过 `POST /api/threads` 显式创建线程，服务端 SHALL 返回权威 `thread_id`。
- 同步聊天 SHALL 要求有效 `thread_id`；缺少或格式非法的 ID SHALL 返回客户端校验错误。
- 未注册或服务重启后失效的 ID SHALL 返回 HTTP 404 和稳定后端 code `thread_not_found`，不得静默创建空线程。
- 合法格式 SHALL 使用高熵、不透明标识；具体 UUID 版本属于实现选择。
- 删除空闲线程 SHALL 同时清理线程元数据和 `InMemorySaver` 中该线程的 checkpoints、pending writes 与 blobs。
- 删除不存在的空闲线程 SHALL 幂等返回 HTTP 204，便于清理服务重启后遗留的浏览器引用。
- 进程退出或重启 SHALL 清空 M01 后端状态；M01 SHALL NOT 声称支持恢复。
- 不同线程 SHALL 允许并发执行。
- 同线程已有同步请求执行时，第二个请求 SHALL 返回 HTTP 409 和后端 code `thread_busy`，不得排队或并行修改历史。
- 删除活跃线程 SHALL 返回 HTTP 409 和后端 code `thread_active`。

## 5. 同步聊天 API

M01 SHALL 保留同步 `POST /api/chat`，请求包含 `message` 和必填 `thread_id`，成功响应至少包含权威 `thread_id` 与完整 `answer`。

- 空白消息 SHALL 继续返回客户端错误，且不创建或改变 checkpoint。
- 非法 ID、未知 ID、忙碌线程和模型失败 SHALL 使用稳定、安全且可测试的错误结构。
- 内部异常、栈和凭据 SHALL NOT 返回客户端。
- M01 SHALL NOT 提供服务端线程列表、对话历史读取或线程 status 查询接口；`idle/busy` 只用于服务端并发控制。
- SSE、token 事件、取消端点和断线行为 SHALL NOT 属于 M01。

## 6. Web UI

- Web UI SHALL 支持新建、切换和删除会话，并在每次聊天中使用当前权威 `thread_id`。
- 页面切换 SHALL NOT 把一个线程的回答写入另一个线程的显示区域。
- 模型失败后，UI SHALL 保留对应用户消息并显示通用失败与重试状态；失败轮次 SHALL NOT 被表现为已进入模型记忆。
- M01 只要求后端暴露稳定错误 code；Web UI SHALL NOT 被要求显示 `thread_not_found` 等技术字符串，具体提示文案与错误映射可由后续 UI 演进修改。
- 删除前 UI SHALL 请求用户确认，确认后先调用后端删除；只有后端成功时才移除本地记录。
- 浏览器 SHALL 在 localStorage 保存完整可见消息、标题、排序和权威 `thread_id`，页面刷新后继续显示这些记录。
- 当聊天请求返回后端 `thread_not_found` 时，UI SHALL 把该本地会话标记为上下文已失效并变为只读，保留全部可见记录，同时要求用户新建对话；UI SHALL NOT 把旧记录静默绑定到一个新空线程。
- UI SHALL 明确说明 M01 的模型上下文只在当前服务进程内有效。

浏览器保存的完整可见记录与 LangGraph State SHALL 是不同的数据层：UI 可以显示超过 5 轮的历史，但不得据此声称模型仍能看到这些记录，也不得在没有明确契约时把完整本地记录重新提交给模型。

## 7. 相邻模块边界

- M02 定义 SSE、token streaming、目标运行取消、客户端断开和流中错误。
- M03 定义持久化 checkpointer、服务重启恢复、迁移与数据库清理。
- M04 定义 `owner_id`、身份、授权和跨用户数据边界。
- M05/M07/M08 定义偏好、长期语义记忆和记忆治理。
- 归档、文件夹、分叉与导出建议在 M03 建立持久会话事实源后，由待单独批准的 `M03A conversation-library` 模块定义；本规格不授权新增该路线模块或实现其功能。

## 8. 验收基线

后续实现 SHALL 使用不访问网络的可控假模型证明：

- 同线程多轮可见，不同线程互不可见；
- 不同线程并发不串状态；
- 历史窗口正确且不拆轮；
- 模型失败不提交半轮；
- 线程创建、未知、删除和重启失效符合已确认契约；
- 同线程重入与活跃删除符合已确认契约；
- Web UI 新建、切换、失败和删除不会影响错误线程。
