# Outcome

完成 `M02 streaming-run-lifecycle` 的独立专项审计，明确旧参考实现中 SSE、token 流、取消、断开与错误行为的可取舍边界，并在用户批准模块方向后形成可由后续独立实现 change 直接使用的完整目标规格。

# Scope

- 审计 VenAgent 当前 M01 同步聊天、线程 busy lease、LangGraph 提交边界、模型 adapter 与 Web UI。
- 审计保留在 `final/` 中的参考实现：SSE 事件、模型 token 转发、请求注册、取消端点、浏览器 AbortController、断开清理和流中错误。
- 把 M02 拆成可独立取舍的 SSE 协议、模型流、运行身份、目标取消、断开处理、终态/错误、同步兼容和最小 UI 子能力。
- 记录模块整体与子能力的 `adopt`、`partial`、`replace`、`drop` 或 `defer` 取舍。
- 在方向获批后定义 M02 的 API/事件、状态转换、M01 上下文提交边界、错误结果和验收标准。
- 本 change 只产出审计与完整目标规格，不修改运行时代码。

# Non-goals

- 不在本 change 实现 SSE、token streaming、取消端点、Web UI 或测试变化。
- 不引入跨进程运行恢复、断线续传、事件回放或持久运行记录；这些能力需要 M03、M15 或后续独立模块的证据与批准。
- 不引入身份、所有权或授权；这些属于 M04，M02 的 `thread_id` 或 `run_id` 不能被描述为授权凭据。
- 不提前定义工具、RAG、任务规划或子 Agent 的领域事件；相应模块获批后才能扩展事件类型。
- 不迁移 `final/` 的后台线程、全局 cancel registry、手写上游 SSE 客户端或旧前端源码。
- 不改变 M01 已批准的同步 `POST /api/chat`、线程窗口、线程隔离和失败不提交契约，除非新的显式决定与规格替换获得批准。

# Acceptance examples

- 审计能用仓库文件证明当前 VenAgent 只有同步聊天、没有运行身份或取消注册表，且 M01 只在模型完整成功后提交一轮。
- 审计能用 `final/` 文件证明旧取消端点会取消所有 in-flight 请求，而不是只取消用户指定的运行。
- 审计能区分 HTTP 建流前错误与建流后错误，并指出旧协议把流中异常包装成普通 `done` 的歧义。
- 审计明确浏览器主动停止、网络断开、服务端取消和上游模型结束不是同一个状态，也不能共享含糊的“已中断”结果。
- 用户选择整体方向后，每个纳入 M02 的子能力都有明确状态、理由、排除项和依赖影响。
- 若用户选择 `replace` 或 `partial`，完整目标规格必须定义开始、增量和唯一终态事件，目标运行取消，以及成功、失败、取消对 M01 committed messages 的影响。
- 本审计 change 不产生运行时代码变化；后续实现 change 必须使用离线可控模型验证，不访问网络或真实凭据。

# Constraints and invariants

- 遵循 canonical `refactor-roadmap`：每个模块先独立审计、取舍和批准，再由独立 change 实现。
- `AGI-saber`/`final` 只作为功能、行为和风险参考，不作为源码迁移目标。
- M01 的 `thread_id` 是对话上下文身份；M02 如引入 `run_id`，两者必须分开建模。
- 同一线程仍只有一个活跃聊天运行；目标取消不得影响其他线程或其他运行。
- 只有完整成功的 user/assistant 对可以进入 M01 committed messages；取消、断开或模型错误不得提交半轮。
- SSE 响应一旦建立，错误必须通过稳定流内事件表达，不能假装为普通成功，也不能泄露上游异常细节。
- Web UI、API、安全错误和验证随 M02 最小交付，不统一延期到 M18。
- 当前 change 保持 Shape；所有用户可见分支与最终共享理解确认完成前不得进入 Build。

# Decisions

- M02 的稳定 capability ID 为 `streaming-run-lifecycle`。
- 当前 change 名为 `audit-streaming-run-lifecycle`，只负责专项审计与完整目标规格；运行时代码由后续独立 change 实现。
- canonical 路线已把 M02 边界限定为 SSE 事件、token 流、目标运行取消、客户端断开和流中错误。
- 用户已确认 M02 整体选择 `replace`：保留实时增量输出和可停止运行的产品目标，替换旧全局取消、后台 daemon thread、含糊终态与同步自动重发方法。
- token streaming 不在本审计 change 中实现；它将在本 change 完成 Shape、Verify、Archive 后，由独立的 M02 实现 change 在 M03 之前进入 Build 实现和验证。
- 用户确认保留两条明确路径：同步 `POST /api/chat` 继续返回 JSON，新增流式 `POST /api/chat/stream` 返回 SSE；不通过同一路径的 `Accept` 协商合并。
- 用户确认客户端主动关闭 SSE 或网络断开时，对该 `run_id` 发起协作式取消；运行真正收口前线程保持 busy，不提供断线续传或后台继续完成。
- 用户确认每条 SSE 流恰有一个明确终态事件：`completed`、`cancelled` 或 `error`。UI 可以保留 partial token 并标记未完成，但只有 `completed` 的完整 user/assistant 对写入 M01 committed messages。
- 用户确认目标取消使用 `POST /api/runs/{run_id}/cancel` 立即返回 accepted；该响应只表示取消信号已接收，SSE 终态才是运行最终结果。
- 同步或流式请求不会在失败后自动重发另一种聊天 API；重试只能由用户显式触发并创建新的运行。
- 用户确认 `token` 事件直接转发 provider/LangChain 的非空文本 delta；不强制重切为逐字符或逐 tokenizer token。
- 用户确认 `completed` 终态携带完整最终 `answer`，供客户端与已拼接 token 对账。
- 用户确认 M02 只保存 active run：重复取消 active run 返回 accepted，格式非法的 run ID 返回 400，未知或已结束 run 返回 404，不提供 run status API 或终态查询。
- 用户已批准本 brief、专项审计与 `streaming-run-lifecycle` 拟议完整规格所述的 M02 最终共享契约。

# Open questions

- 无。

# Verification expectations

- 审计结论必须可由 canonical 规格、`venagent/` 当前实现、`tests/` 和 `final/` 参考实现复核，不依赖聊天记忆。
- 规格必须保持 M01/M02/M03/M04/M15 边界，不把持久恢复、所有权或可靠并行运行偷渡进 M02。
- 后续实现验证至少覆盖事件顺序与唯一终态、真实增量块、目标取消隔离、客户端断开、队列背压、上游流错误、同步 API 保留和失败不提交。
- 测试必须覆盖 cancel/complete 竞态：先形成的终态为唯一权威结果；取消请求不能把已经完成并提交的运行改写为 cancelled。
- 所有验证使用可控 fake model/stream，不访问真实 provider、网络或凭据。
- Batch 模式下，本轮只询问前置条件已经满足的问题；整体方向确认后再计算事件、取消和断开等下一轮问题。
