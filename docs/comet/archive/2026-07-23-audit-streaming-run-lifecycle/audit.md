# M02 streaming-run-lifecycle 专项审计

## 审计结论

M02 的产品目标值得保留：用户应当在模型生成时看到增量文本，能停止自己正在看的那一次运行，并能明确区分完成、取消、断开和失败。但旧参考实现的方法不应沿用。它虽然为每次 SSE 请求生成 `request_id`，取消 API 却调用进程级 `agent.cancel()`，会向所有 in-flight token 广播；断开后只等待后台 daemon thread 0.5 秒；流中异常被包装成 HTTP 200 下的普通 `done`；浏览器在流端点返回非 2xx 时还会自动重发同步请求，存在重复执行风险。

因此本审计建议 M02 整体状态为 `replace`：采用 SSE 与真实 provider 增量输出的产品目标，用 M01 的线程 lease、独立 `run_id`、目标取消注册表、明确终态事件和“成功才提交完整轮次”的新契约重做。用户已确认这一整体取舍。

token streaming 的代码实现不属于本审计 change；本 change 归档后应立即创建独立的 M02 实现 change，在 M03 之前完成流式运行生命周期的实现与验证。

## VenAgent 当前事实

- `venagent/api.py` 只提供同步 `POST /api/chat`；请求包含 `thread_id` 与 `message`，成功返回完整 `answer`，没有 SSE 路由、运行身份或取消端点。
- `venagent/conversation.py` 的 `ThreadRegistry` 只保存线程存在性与一个 `busy` 布尔值。lease 覆盖整次模型调用，同线程重入返回 `thread_busy`，但没有可定位活跃运行的 `run_id` 或 cancel handle。
- `venagent/agent_loop.py` 的模型边界只声明 `invoke()`。图节点在模型完整返回 `AIMessage` 后才一次性写入 user/assistant 对；模型抛错不会提交半轮。这一 M01 不变量必须在流式实现中保留。
- `venagent/llm.py` 通过 LangChain 官方 chat model adapter 装配 OpenAI、OpenAI-compatible、Azure OpenAI、Anthropic 和 Google GenAI。adapter 本身具备公开流式边界，但当前 `MessageInvoker` 没有暴露或规范化 chunk。
- `venagent/web/index.html` 以 `runtime.pending` 阻止同线程重复发送，只会等待同步 JSON 响应；没有增量 assistant bubble、停止按钮、运行 ID或终态显示。
- 当前测试覆盖线程创建、隔离、busy、失败不提交、删除和同步错误；没有事件顺序、流中错误、断开或目标取消测试。

## 参考实现的直接证据

### SSE 有增量能力，但协议混合多种职责

- `final/internal/handler/handler.py` 的 `/api/chat/stream` 生成 `start`、`route`、`memory`、`step`、`tool_call`、`rag_result`、`token`、`done`，最后再发送 OpenAI 风格 `data: [DONE]`。
- M02 当前只覆盖基础聊天运行生命周期。旧协议提前混入记忆、工具、RAG 和 ReAct 事件，会绕过后续模块的独立审计与批准。
- endpoint 使用后台 daemon thread 把同步 agent 回调桥接到有界 `asyncio.Queue(maxsize=256)`。队列满时触发 cancel，但没有稳定的 `backpressure` 错误终态保证。

### 请求有 ID，取消却不是目标取消

- handler 为每个流生成 `request_id` 并写入事件数据，但 `/api/chat/cancel` 不接收该 ID。
- `final/internal/agent/cancel.py` 的 `CancelRegistry.cancel_all()` 遍历全部 token；`agent.cancel()` 因而可能停止其他并发线程的运行。
- 浏览器 `stopChat()` 先 abort 当前 fetch，再调用无目标的 `/api/chat/cancel`。UI 看似停止当前消息，服务端语义却是进程级广播。

### 断开与终态不可靠

- SSE generator 的 `finally` 会 cancel token，但只对 worker `join` 0.5 秒；如果底层调用没有及时响应取消，daemon thread 仍可继续执行副作用或写入状态。
- worker 异常被转换为 `done`，数据里放通用失败 answer 和 `success: false`，没有独立稳定 `error` 终态，也没有错误 code。
- 正常完成、取消和失败都共享 `done`，客户端还要同时理解 `[DONE]` sentinel；唯一终态和状态机不清晰。
- `final/internal/agent/agent.py` 的 `_prepare()` 在模型或工具执行前就写入 user 历史；取消或失败可能留下半轮，违反 M01 已批准的成功后提交契约。

### 浏览器存在重复执行与错误丢失风险

- 旧前端在 `/api/chat/stream` 返回非 2xx 时自动调用同步 `/api/chat` 重试同一消息。若服务端实际已经开始运行但响应层失败，可能重复执行。
- 前端遇到 AbortError 会保存一条“已中断”，但没有区分“服务端已确认取消”与“浏览器只是停止读取”。
- 旧解析器对无法解析的事件数据直接跳过，断流后也没有检查是否收到合法终态，可能把截断响应当作普通结束。

## 子能力取舍建议

| 子能力 | 建议 | 理由与边界 |
| --- | --- | --- |
| SSE 增量体验 | `adopt` | 保留单请求持续推送与 assistant 文本渐进显示的产品目标。 |
| 旧事件协议 | `replace` | 只定义 M02 所需的开始、文本增量和唯一终态；工具、RAG、记忆事件留给相应模块。 |
| LangChain provider token 流 | `adopt` | 使用公开 model streaming 边界并规范化文本 chunk；不保留手写 `requests` 上游 SSE 客户端。 |
| 运行身份 | `replace` | 新增服务端生成的不透明 `run_id`，与 `thread_id` 分离；旧 `request_id` 仅出现在事件里且未形成生命周期边界。 |
| 取消 | `replace` | 只向指定活跃 `run_id` 发出幂等协作式取消，不提供进程级 cancel-all。 |
| 客户端断开 | `replace` | 默认建议把断开视为该运行的取消请求，并等待运行真正收口后释放线程 lease；不声称立即杀死 provider。 |
| 流中错误 | `replace` | 建流前使用稳定 HTTP 错误；建流后发出稳定 error 终态与安全 code，不泄露上游详情。 |
| 同步 `/api/chat` | `adopt` | M01 已要求保留；M02 不用 SSE 替换或删除同步 API。 |
| 自动同步回退 | `drop` | 不在流失败时静默重发同一消息，避免重复模型调用或未来工具副作用。 |
| 断线续传/事件回放 | `defer` | 需要持久 run/event 与可靠恢复，超出进程内 M02，后续由 M03/M15 或独立模块评估。 |
| 工具/RAG/记忆/计划事件 | `defer` | 相应模块尚未获批，M02 只保留可扩展 envelope，不预建领域事件。 |

## 推荐的 M02 边界

如果用户批准整体 `replace`，下一步应逐项确认并形成完整目标规格：

1. 流请求继续携带 M01 的有效 `thread_id` 与 `message`，服务端为本次执行生成独立 `run_id`。
2. SSE 只包含协议版本、事件序号、`thread_id`、`run_id` 和当前模块需要的数据；每条流恰有一个完成、取消或错误终态。
3. 只有完整完成才把 user/assistant 对提交给 M01 checkpointer；取消、断开和错误保留可见的临时部分文本，但不进入后续模型上下文。
4. 取消 API 只作用于指定 `run_id`，不会影响其他线程；取消信号的“已接受”和运行真正“已取消”是两个可区分时刻。
5. 客户端主动停止与网络断开都请求取消该运行；UI 只有收到终态时才把结果标记为服务端确认，异常断流显示为连接丢失。
6. 同步 `/api/chat` 保持原契约；流请求失败不自动重发同步调用。
7. 不提供跨连接续传、历史事件回放、运行列表或持久状态查询。

## API 路径决策说明

`POST /api/chat` 与 `POST /api/chat/stream` 可以技术上合并为一个路径，通过 `Accept` 协商 JSON 或 `text/event-stream`。但这会让同一路径同时承担两种响应 framing、建流前/建流后错误语义和不同客户端超时策略；OpenAPI 也需要为同一操作描述两套响应。保留两条路径则能让 M01 的同步 JSON 契约保持不变，并使流式端点显式表达连接型生命周期。

本 change 不替用户选定其中一种；该选择记录在 brief 的 blocking Q1。

## 与相邻模块的边界

- M01 继续负责线程身份、最近五个成功轮次、线程隔离和进程内 checkpointer。M02 不能让 partial token 成为 committed messages。
- M03 才负责重启后对话/checkpoint 恢复；若未来需要 SSE 断线续传，也必须先有可持久化的运行与事件证据。
- M04 才负责 owner、鉴权和跨用户授权。M02 的 target cancel 在当前阶段只适合单用户或受信环境。
- M06 以后才定义工具循环；M07/M08 定义记忆；M12/M13 定义 RAG；M14/M16 定义计划与子 Agent。M02 不预先批准这些事件。
- M15 才处理可靠并行、幂等、重试、checkpoint 恢复和复杂部分失败。M02 只处理同线程单活跃运行的最小生命周期。

## 风险与验证重点

- 取消通常是协作式信号，provider 或 transport 未必立即停止；必须在真实执行收口前保持线程 busy，不能把“已接受取消”伪装成“已经停止”。
- SSE 在响应头发出后不能改 HTTP 状态；测试必须分别覆盖建流前验证错误和建流后 terminal error。
- LangChain 各 provider 的 chunk 结构不同；规范化层必须只输出公开文本内容，过滤空块、usage 和 reasoning metadata，且不能把对象 repr 发送给浏览器。
- 客户端断开、队列背压和取消可能并发发生；运行注册、lease 释放和终态生成必须幂等，不能重复终态或泄漏 busy。
- 浏览器异常断流时可能已有部分文本；UI 必须保留为明确的未完成显示，不能当作成功回复，也不能进入后端 committed history。
- 验证应使用同步与流式 fake model、可控阻塞点和 ASGI disconnect，不访问真实网络或凭据。
