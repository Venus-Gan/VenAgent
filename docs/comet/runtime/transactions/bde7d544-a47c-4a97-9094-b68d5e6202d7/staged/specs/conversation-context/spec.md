# Conversation Context 完整目标规格

## 1. 目标与术语

VenAgent SHALL 以 `Conversation` 表示 owner-scoped 对话容器，以不可变的 `ConversationMessage` 表示正式消息，以 `AgentRun` 表示针对一条 user message 的执行尝试。对话历史、运行生命周期与模型调用上下文是三个不同概念，不得再用成对 turn 或 conversation checkpoint 合并表达。

业务标识 SHALL 使用 `conversation_id`、`message_id`、`run_id` 和 `owner_id`。LangGraph adapter 内的 `thread_id` 只映射单个 `run_id`，不得作为 conversation 标识进入领域接口。

## 2. Conversation

- Conversation 至少包含 `conversation_id`、`owner_id`、`owner_kind`、`lifecycle_state`、`title`、`title_source`、`created_at`、`updated_at`、`last_successful_at` 和删除时间。
- lifecycle 至少区分 `active|deleting`；deleting 对用户不可见、不可新建 run，并通过可恢复维护流程完成消息、run、grant 和 checkpoint 清理。
- 所有读取、改名、删除、消息与 run 操作按当前 owner 授权；不存在与跨 owner 访问返回同一安全错误。
- 列表使用稳定 cursor，按 `updated_at,conversation_id` 排序；不得混入其他 owner 或删除中的对象。
- 标题可由首次成功提交派生或由用户手工修改。失败、取消和 partial 不推进 `last_successful_at`，也不自动成为标题来源。

## 3. ConversationMessage

- 正式消息至少包含 `message_id`、`conversation_id`、`owner_id`、`role=user|assistant`、`content`、稳定顺序、`created_at`；user message 保存 `client_request_id`，assistant message保存 `source_run_id` 与 `reply_to_message_id`。
- 输入通过边界校验且创建事务提交后，user message 即为不可变业务事实；模型失败或用户取消不删除该消息。
- assistant message 只在成功 finalizer 的业务事务中创建。失败、取消、等待审批、不兼容、进度和流式 partial 不得伪造成 assistant message。
- 数据库 SHALL 保证 `assistant.source_run_id` 唯一、`assistant.reply_to_message_id` 唯一；同一 run 只能发布一个最终回答，同一 user message 最多拥有一个成功回答。
- 重复 `client_request_id` 且请求语义一致时返回原 message/run；相同 ID 携带不同文本、conversation 或操作时返回幂等冲突。
- 当前不支持编辑正式消息、重新生成成功回答、回答版本、分支或候选回答切换。

## 4. Run 与消息关联

- 初次发送 SHALL 在一个业务事务中写入 user message、`AgentRun(status=queued)`、RunGrant 和 conversation 单活跃占用；事务提交前不得启动 LangGraph。
- `AgentRun.input_message_id` 指向 user message；仅成功后 `output_message_id` 指向 assistant message。
- 失败、取消或不兼容 run 可由显式 retry 创建新 run，并复用原 `input_message_id`；原 run 永不复活或改写。
- 只有 conversation 最新未完成的 user message、无其他活跃 run且当前 owner/权限有效时才可原地 retry。成功 run 和较早消息不允许原地 retry。
- conversation 详情 SHALL 返回线性正式 messages 与轻量 run summaries；run 详情与实时进度通过 run API 获取。客户端必须通过显式 ID 关联，不得按文本或相邻位置推断。

## 5. 上下文投影

- 数据库消息列表不得直接作为模型 prompt。应用层使用无状态 `ProjectionInputCollector` 从 conversation、当前 run/State、身份能力和后续 provider 收集类型明确的候选输入，再交给纯 `ContextProjectionService` 过滤、编排和预算。
- 本 change 的默认投影只采用：系统能力/安全摘要、当前任务输入、有限的近期成功对话、当前执行摘要；不得把失败 partial、原始异常、完整 State、grant、凭据或 checkpoint 内容注入 prompt。
- 输出使用统一 `ContextBlock`，至少表达稳定 section、内容、来源引用、可见角色、优先级、token 估算和截断/舍弃原因；最终 `ContextProjection` 与 `BudgetReport` 是一次调用的派生值，不成为第二套持久状态。
- section/filter/mode/槽位编排是 M05/M06/M07 可修订的策略契约。本 change 只建立扩展点和确定性默认策略，不预建通用规则引擎或硬编码未来 provider。
- 正式消息是否进入长期记忆、失败尝试是否可提取事实以及 RAG evidence 的选择，分别留给 M05/M08；运行成功不是唯一提取条件，当前基础不得自动写长期记忆。

## 6. 删除与保留

- 删除 conversation 先原子标记 deleting 并阻止新 run，再请求所有非终态 run 取消，等待 M06/运行事实收敛后删除业务记录、RunGrant 和对应 `run_id` checkpoint。
- owner 删除使其全部 conversation、messages、runs 和 grants 立即不可访问，并由可重试维护流程清理；日志不得成为正文或身份数据的旁路副本。
- 普通 session 失效不删除业务消息；owner/guest 生命周期策略决定保留期限。temporary 模式的数据只存在进程内且重启丢失。
- 清理 checkpointer 只能使用公开 `delete_thread(run_id)` 一类契约，不查询或修改 LangGraph 私有表。

## 7. API 与前端投影

- HTTP 提供 conversation 创建、列表、详情、改名和删除，以及 `POST /api/conversations/{conversation_id}/runs`；旧 `/api/threads` 与 `/api/chat*` 不属于目标契约。
- 前端 SHALL 分离正式 `messagesByConversation`、`runsById` 与内存 `partialByRunId`，再由纯 selector 形成线性时间线。
- 发送时可以显示 user message 的提交中状态，但不得预造正式 assistant message。服务端确认后使用正式 user message；成功后使用正式 assistant message完整替换 partial。
- 同一 user message 的多个失败尝试默认折叠显示，用户可查看安全摘要；成功 assistant message仍是普通对话消息。
- 身份变化时停止旧 owner 的观察连接并隐藏/清除其缓存；不得跨 owner 合并 conversation、message、run 或 partial。

## 8. 验收

- 证明 conversation/message/run 标识与 owner 隔离，线性顺序、幂等创建、单成功回答和 latest-unfinished retry 规则正确。
- 证明失败、取消、断线和刷新不会创建正式 assistant message或污染下一次模型上下文。
- 证明默认 ContextProjection 确定、预算可测、来源可追踪、秘密不进入 prompt，并可在后续模块替换策略而不改变消息/State 所有权。
- 证明删除中对象不可访问、清理可重试、temporary 重启丢失且 durable 重启恢复正式消息。
- 真实浏览器证明正式消息、run 尝试、partial 和终态替换没有重复、串线或跨身份泄露。
