# Streaming Run Lifecycle 完整目标规格

## 1. 模块取舍

M02 `streaming-run-lifecycle` 的整体状态为 `replace`。

VenAgent SHALL 保留 SSE 增量输出、真实模型文本流和用户停止当前运行的产品目标，但 SHALL NOT 沿用旧参考实现的进程级 cancel-all、后台 daemon thread 生命周期、混合领域事件、含糊 `done` 终态、手写 provider SSE 客户端或失败后同步自动重发。

本审计 change 只定义完整目标规格。token streaming、取消与 Web UI 代码 SHALL 在本 change 归档后的独立 M02 实现 change 中完成，并在进入 M03 前实现、验证和归档。

## 2. 能力目标与边界

`streaming-run-lifecycle` SHALL 在 M01 对话线程上增加单次运行身份、SSE 文本增量、目标取消、断开取消和明确终态，同时保持 M01 的线程隔离、最近五个成功轮次和失败不提交不变量。

- `thread_id` SHALL 继续表示对话上下文；`run_id` SHALL 表示一次具体聊天执行，两者不得混用。
- M02 的运行与取消状态 SHALL 只在当前服务进程内有效，不承诺跨进程恢复。
- M02 SHALL NOT 提供断线续传、事件回放、后台继续完成、持久运行记录或 Last-Event-ID 恢复。
- M02 SHALL NOT 定义工具、RAG、记忆、计划或子 Agent 的领域事件。
- `thread_id` 与 `run_id` 都不是身份或授权凭据；M04 完成前该能力只适合单用户或受信环境。

## 3. 运行身份与并发

- 流式请求通过 M01 的消息与线程校验并成功取得线程 lease 后，服务端 SHALL 生成高熵、不透明、规范格式的 `run_id`。
- `run_id` SHALL 与 active thread entry 绑定，并对应唯一协作式取消信号。
- 同一线程的同步与流式聊天共享单活跃运行边界；线程 busy 时新的同步或流式聊天 SHALL 返回 HTTP 409 和稳定 code `thread_busy`。
- 不同线程 SHALL 可并发运行；取消一个 `run_id` SHALL NOT 影响其他线程或运行。
- 删除存在活跃运行的线程 SHALL 继续返回 HTTP 409 和 `thread_active`。
- 运行注册、终态形成、取消和 lease 释放 SHALL 幂等；每个运行最多形成一个终态。
- 完成与取消并发时，先被服务端原子确认的终态 SHALL 成为唯一权威结果。已完成并提交的运行不得被后到的取消改写。

## 4. 聊天 API 与 SSE 协议

### 同步聊天

同步 `POST /api/chat` SHALL 保持 M01 JSON 请求、成功响应和错误契约，不被删除，也不通过 `Accept` 改成双响应模式。

### 流式聊天

新增 `POST /api/chat/stream`，请求 SHALL 包含有效 `thread_id` 与非空 `message`，成功响应使用 `text/event-stream`。

- 建立 SSE 响应前发现的非法请求、未知线程或 busy 线程 SHALL 使用 M01 的稳定 HTTP JSON 错误。
- 建流后出现的模型、传输、背压或内部失败 SHALL 使用 `error` 终态和稳定安全 code 表达，不得泄露上游异常、栈、URL 或凭据。
- 第一条业务事件 SHALL 是 `started`，至少包含协议版本、单调递增序号、权威 `thread_id` 和 `run_id`。
- 后续 `token` 事件 SHALL 只携带非空公开文本 delta；usage、reasoning metadata、对象 repr 和空 chunk SHALL NOT 作为回答文本发送。
- 每条流 SHALL 恰有一个业务终态：`completed`、`cancelled` 或 `error`。终态之后 SHALL NOT 再发送业务事件。
- 显式终态事件与连接关闭共同结束响应；M02 SHALL NOT 同时要求旧 OpenAI 风格 `data: [DONE]` 作为第二套业务终态。
- 服务端 SHALL 在等待 provider 输出期间周期性发送不改变业务事件序号的 SSE heartbeat，以便客户端与代理识别仍存活的连接；heartbeat 不属于业务终态，也不得进入回答文本。
- 客户端或服务端不得在流失败后自动调用同步 `/api/chat` 重发同一消息。

`token` 事件 SHALL 直接转发 provider/LangChain 产生的非空公开文本 delta；单个事件可能包含多个字符或 token，M02 SHALL NOT 强制按字符或 tokenizer 重切。`completed` 终态 SHALL 携带完整最终 `answer`，客户端可用它与已拼接 token 对账。

## 5. 提交、取消与断开

- 模型完整成功且服务端原子形成 `completed` 终态后，当前 user/assistant 对才 SHALL 作为完整轮次提交到 M01 committed messages。
- `cancelled`、`error` 或异常断流 SHALL NOT 把 pending user、partial assistant 文本或半轮写入后续模型可见历史。
- UI MAY 保留已经收到的 partial token，但 SHALL 明确标记为已取消或失败，不得表现为成功回复。
- `POST /api/runs/{run_id}/cancel` SHALL 只向指定 active run 发出协作式取消信号，并立即返回 accepted；该响应不表示 provider 已停止。
- 运行真正收口前，所属线程 SHALL 保持 busy；SSE 的 `cancelled`、`completed` 或 `error` 终态才是权威最终结果。
- 客户端主动关闭响应体、页面离开或服务端检测到网络断开时，SHALL 对该 `run_id` 发起与显式停止相同的协作式取消。
- 断开检测和 provider 取消可能延迟；M02 SHALL NOT 声称能强制立即终止任意上游 provider。
- 取消 active run 的重复请求 SHALL 不触发第二次副作用。
- 格式非法的 `run_id` SHALL 返回 HTTP 400 和稳定 code `invalid_run_id`。
- 未知或已结束的 `run_id` SHALL 返回 HTTP 404 和稳定 code `run_not_found`。
- M02 SHALL 只保存 active run，不提供 run status API 或已结束终态查询；持久化运行结果属于后续模块。

## 6. Web UI

- Web UI SHALL 对当前 active run 渐进渲染 `token` 文本，并在运行期间把发送按钮切换为明确的停止操作。
- 停止操作 SHALL 使用当前 `run_id` 调用目标取消 API，不调用进程级全局取消。
- UI SHALL 区分“取消请求已接受”与服务端最终 `cancelled`；accepted 响应不得立即伪装成运行已经停止。
- `completed` SHALL 显示为成功 assistant 回复；`cancelled` 和 `error` SHALL 保留已有 partial 文本并显示不同的未完成状态。
- 浏览器只关闭本地读取但尚未收到服务端终态时，SHALL 显示连接丢失或正在取消，不得自行宣称 completed。
- 浏览器读取到 EOF、读取异常或活动超时且尚未收到业务终态时，SHALL 把当前尝试收敛为连接中断、释放本地运行资源并允许用户显式重试；不得永久停留在发送、思考或生成状态。
- UI SHALL 在 `started` 前显示用户消息“发送中”，在 `started` 后把用户消息视为已发送并让 assistant 显示“思考中”，首个 `token` 后显示“生成中”。主动停止后只有 assistant 显示“已停止生成”，不得把已到达服务端的用户消息标为发送失败。
- 取消或错误后的重试 SHALL 由用户显式触发，并创建新的 `run_id`；不得静默自动重发。
- 页面切换、跨线程并发和延迟终态 SHALL NOT 把一个线程的 token 或状态写入另一个线程的 UI。

## 7. 相邻模块边界

- M01 继续负责线程创建、上下文隔离、最近五个完整成功轮次、同步 API 和进程内 checkpointer。
- M03 才负责 conversation/checkpoint 持久化和重启恢复；M02 不自动获得运行结果持久化或断线续传。
- M04 才负责 owner、身份、授权和 target cancel 的跨用户权限边界。
- M06 定义受控外部工具与 sandbox；M07 才定义工具循环、计划、子 Agent、可靠并行与恢复；M05 定义记忆；M08 定义 RAG。相应事件不得在 M02 中预建。未来若选择断线后继续并恢复，必须通过新的明确规格修改，不得静默改变 M02 的断开即取消行为。

## 8. 验收基线

后续 M02 实现 SHALL 使用无网络、无真实凭据的可控 fake model/stream 证明：

- `/api/chat` 的 M01 同步 JSON 契约保持不变，`/api/chat/stream` 独立提供 SSE；
- 每条成功流按顺序产生 `started`、一个或多个可验证文本 delta 和唯一 `completed`；
- 取消流只产生唯一 `cancelled`，模型错误只产生唯一 `error`，且不会再产生 completed；
- 目标取消只影响指定 `run_id`，不同线程的并发运行不被误取消；
- 客户端断开会请求取消，运行收口前线程保持 busy，收口后 lease 必定释放；
- completed 才提交完整轮次，cancelled/error/断流均不提交半轮；
- 建流前错误使用稳定 JSON HTTP code，建流后错误使用安全的 SSE error 终态；
- 队列背压、取消/完成竞态和重复取消不会造成重复终态、死锁或 busy 泄漏；
- heartbeat、无终态 EOF、读取异常和活动超时不会造成永久 busy；Web UI 能增量渲染、区分发送/思考/生成/停止/中断、保留并标记 partial 文本，并且不会自动同步重发。

## 9. 已确认的运行生命周期边界

- `token` 事件直接转发 provider/LangChain 非空文本 delta，不强制重切粒度。
- `completed` 携带完整最终 `answer`。
- 运行注册表只保存 active run；重复取消 active run 返回 accepted，格式非法 ID 返回 400，未知或已结束 ID 返回 404，不提供 status API。
