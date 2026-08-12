# Outcome

完成 `M01 conversation-context` 的独立专项审计和完整目标规格：保留多轮会话与有限窗口的产品目标，替换 AGI-saber 按 `userID` 共享 STM 的方法，改用 LangGraph `thread_id`、进程内 checkpointer 和明确的线程生命周期。

# Scope

- 审计 AGI-saber 的浏览器会话、短期历史分桶、历史截断、持久化预热和失败写入顺序。
- 审计 VenAgent 当前 Agent Loop、同步 API、Web UI 和测试中的 M01 能力与缺口。
- 定义 `thread_id` 创建与未知线程语义、有限多轮上下文、线程隔离、进程内 checkpointer 和同步请求并发边界。
- 定义 M01 最小线程 API、同步聊天错误行为和随模块交付的 Web UI 会话体验。
- 形成后续独立实现 change 可直接使用和验收的 `conversation-context` 完整目标规格。
- 本 change 只产出审计与规格，不修改运行时代码。

# Non-goals

- 不在本 change 实现 Agent Loop、API、Web UI 或测试变化。
- 不审计或定义 SSE、token 流、目标取消、断线和流式错误；这些属于 M02。
- 不引入持久化 checkpointer、服务重启恢复或数据库迁移；这些属于 M03。
- 不引入用户身份、所有权或鉴权；这些属于 M04。
- 不引入偏好、长期语义记忆、RAG、工具、MCP、任务规划或子 Agent。
- 不迁移 AGI-saber 的 Go/Vue 源码。

# Acceptance examples

- 同一个 `thread_id` 的第二次成功请求能看到该线程窗口内的完整历史；线程 A 与线程 B 互不可见。
- 历史只包含完整成功的 user/assistant 对；模型失败不会把半轮带入下一次模型输入。
- 超出已确认窗口的最旧完整轮次不再进入后端上下文，且不会拆开消息对。
- 不同线程允许并发；同线程重入和活跃删除遵循已确认的确定性行为。
- 新建、未知、重启后失效和删除线程遵循已确认的 API 结果，Web UI 不伪装后端仍有已失效的上下文。
- M01 不出现 SSE、流式 token、目标取消或断线恢复契约。
- 浏览器刷新后保留完整可见会话；服务重启导致后端线程失效时，旧记录仍可只读查看，但不能继续冒充有效上下文。

# Constraints and invariants

- 遵循已归档的模块化重构路线：一个模块一次审计、取舍、审批和实现。
- AGI-saber 只作为功能、行为与风险参考，不作为源码迁移目标。
- M01 整体状态已确认为 `replace`；采用 LangGraph `thread_id` 与 `InMemorySaver`，不复刻 `map[userID]*ShortTerm`。
- `thread_id` 只表示对话线程，不表示用户身份，也不能成为授权边界。
- M01 只允许单进程内 checkpointer；多 worker 和跨进程恢复属于后续模块。
- 已提交历史与当前待处理输入必须分离；失败输入不得污染后续模型上下文。
- Web UI、API、安全提示和验证随 M01 最小交付，不统一推迟到 M18。
- M01 强制稳定的后端错误 code，但不强制 Web UI 显示对应技术字符串或完成最终提示文案；前端错误映射与提示词允许后续按 UI 演进修改。
- M01 必须定义可扩展但最小的 LangGraph State；“不建立通用 Agent 状态机”只排除未被当前模块需要的生命周期枚举和未来模块字段。
- 当前变更保持 Shape；用户确认完整 M01 契约前不得进入 Build。

# Decisions

- 用户已确认 M01 整模块选择 `replace`。
- 保留的目标：同线程有限多轮、不同线程隔离、会话 UI 和显式清理。
- 替换的方法：浏览器时间戳 ID、按 `userID` 分桶的自制 STM，以及模型前预写 user 历史。
- M01 的稳定 capability ID 为 `conversation-context`。
- 当前活跃的旧 `phase-1-conversation-runtime` 草案复用于 M01 审计，其原有 M02 内容已移出当前范围。
- 本 change 只定义审计与完整目标规格；运行时代码实现由后续独立 change 承担。
- 线程通过 `POST /api/threads` 显式创建；同步聊天必须携带有效 ID，未知或重启后失效的 ID 返回后端 `404 thread_not_found`。
- 后端只保留最近 5 个完整成功轮次；更早轮次从模型上下文与进程内线程状态中移除。
- 同线程第二个同步请求返回 `409 thread_busy`；删除活跃线程返回 `409 thread_active`；不同线程可以并发。
- M01 不提供服务端线程列表或历史读取接口，只提供新建、聊天和删除；可见历史由浏览器侧管理。
- 同步模型失败时，UI 保留用户消息并显示通用失败与重试状态；失败轮次不进入后端上下文。
- 删除会话前由 UI 确认，后端删除成功后才移除本地记录；删除不存在的空闲线程幂等返回 `204`。
- `thread_not_found` 等稳定错误 code 只要求存在于后端契约和测试；M01 不强制前端显示这些技术字符串，具体提示文案延期优化。
- LangGraph State 至少区分 committed `messages` 与本次 `pending_user`；`thread_id` 通过 config 传入，`idle/busy` 留在服务层线程注册表，不混入图状态。
- State 是后续图能力的扩展基座；工具、计划、审批、产物和子 Agent 字段只在相应模块获批后增加，不预建通用 Agent 生命周期状态机。
- 主流桌面 Agent 的可采用模式是把完整可见会话作为可管理记录，同时把模型上下文单独裁剪；M01 不全量复制归档、文件夹、分叉和导出功能。
- 浏览器 localStorage 保存完整可见消息、标题、排序和 `thread_id`；后端 404 表示上下文失效后，UI 将旧会话标记为只读并要求新建对话，不静默绑定空线程。
- 归档、文件夹、分叉和导出建议在 M03 持久化完成后，作为待单独批准的 `M03A conversation-library` 模块实现；该建议不构成当前路线变更授权。
- 用户已批准本 brief 与 `conversation-context` 拟议完整规格所述的 M01 最终共享契约。

# Open questions

- 无。

# Verification expectations

- 审计结论必须可由 VenAgent 与 AGI-saber 的实际文件复核，不依赖聊天记忆。
- 规格必须严格遵守 M01/M02/M03/M04 边界，不得重新形成旧 Phase 1 的混合包。
- 后续实现验证使用可控假模型，不访问网络或真实凭据。
- 测试至少覆盖同线程多轮、跨线程隔离、窗口边界、失败不提交、同线程并发、未知线程和目标删除。
- Comet Shape 必须保留当前未决行为为 blocking，直到用户明确回答并完成最终共享理解确认。
