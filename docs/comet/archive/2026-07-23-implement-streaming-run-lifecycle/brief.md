# Outcome

实现 canonical `streaming-run-lifecycle` 完整规格：在 M01 线程上下文上增加独立 SSE 流式聊天、真实 LangChain/provider 文本 delta、目标运行取消、断开取消、明确终态和最小 Web UI 流式体验，同时保持同步 API 与成功后提交不变量。

# Scope

- 为每次流式聊天生成独立 `run_id`，维护只包含 active run 的进程内注册表和协作式取消信号。
- 在 Agent Loop/模型公开边界上实现文本 delta 流，并只在完整成功后提交 user/assistant 对。
- 新增 `POST /api/chat/stream` SSE 端点与 `POST /api/runs/{run_id}/cancel` 目标取消端点。
- 定义并编码 `started`、`token`、`completed`、`cancelled`、`error` 事件以及稳定的建流前/建流后错误。
- 更新 Web UI：渐进渲染、停止目标运行、partial 文本状态、显式重试和跨线程隔离。
- 保持轻量模块边界；API 只做传输映射，run registry/cancel、SSE 编码和图提交各自可独立测试。
- 增加离线单元、API 集成和 ASGI 断开验证，且回归现有 M01/LLM 测试。

# Non-goals

- 不删除或改变同步 `POST /api/chat` 的 M01 JSON 契约。
- 不实现断线续传、Last-Event-ID、事件回放、后台继续完成、run status API 或已结束运行查询。
- 不实现跨进程运行恢复、持久 run/event 存储或服务重启后继续；这些属于 M03/M15 或后续显式 change。
- 不引入 owner、鉴权或 target cancel 的跨用户授权；这些属于 M04。
- 不新增工具、RAG、记忆、计划或子 Agent 事件。
- 不迁移 `final/` 的 daemon worker、全局 cancel-all、手写 provider SSE 或前端同步自动回退。
- 不预建完整 domain/application/infrastructure 子目录；M02 只增加当前职责需要的扁平模块。

# Acceptance examples

- 有效流请求按顺序返回 `started`、provider/LangChain 非空文本 delta 和唯一 `completed`；completed 携带完整 answer，delta 拼接结果与它一致。
- 同步 `/api/chat` 继续返回原 JSON；流式 `/api/chat/stream` 独立返回 `text/event-stream`，流失败不自动重发同步请求。
- 取消一个 active `run_id` 立即返回 accepted，最终流只产生 `cancelled`，且不影响其他线程的运行。
- 重复取消同一 active run 仍 accepted；格式非法 ID 返回 400 `invalid_run_id`；未知或已结束 ID 返回 404 `run_not_found`。
- 客户端断开会请求取消，运行真正收口前线程保持 busy，收口后 lease 和 active run 必定释放。
- 只有 `completed` 提交完整 user/assistant 对；cancelled、error、断流和 partial token 不进入 M01 committed messages。
- 建流前非法输入、未知线程和 busy 使用稳定 JSON HTTP 错误；建流后模型或背压失败使用安全 `error` 终态且不泄露内部详情。
- Web UI 渐进显示 token，停止按钮只取消当前 run；cancelled/error 保留 partial 文本并标记未完成，手工重试产生新 run。

# Constraints and invariants

- canonical `docs/comet/specs/streaming-run-lifecycle/spec.md` 是本 change 的权威行为契约；本实现不修改其长期行为。
- M01 的 `thread_id`、ThreadRegistry busy、五轮窗口、失败不提交和线程删除契约必须保持。
- 每个运行最多形成一个终态；完成/取消竞态由服务端原子决定，已完成并提交的运行不得被改写。
- token 只包含公开文本 delta；空 chunk、usage、reasoning metadata 和对象 repr 不得进入回答文本。
- 取消是协作式；取消 accepted 不等于已经停止，lease 必须持续到执行收口。
- 不同线程可以并发，目标取消不得广播到其他 active run。
- 新验证默认无网络、无真实模型、无真实凭据。
- 用户已批准 canonical 完整契约；没有新的用户可见行为分支。

# Decisions

- 本 change 只实现既有 canonical `streaming-run-lifecycle`，不创建或替换 capability spec。
- 运行时代码保持扁平职责模块：现有 `api.py`、`conversation.py`、`agent_loop.py`、`llm.py` 继续各自边界，并按需要新增 `runs.py` 与 `streaming.py`；不提前引入 M03 持久层目录。
- 使用 LangChain/Runnable 公开 streaming 边界，不实现手写 provider SSE client。
- 使用有界异步桥接和显式取消/终态清理；不使用无法收口的旧 daemon worker 模式。
- Web UI 使用 fetch response body 解析 POST SSE，并保存当前 run ID；EventSource 不支持带 JSON body，不作为本端点客户端。
- 当前实现需要真实项目代码与测试，不是 no-code change。

# Open questions

- 无。

# Verification expectations

- 单元测试覆盖 run registry、ID 校验、重复取消、目标隔离和完成/取消竞态。
- Agent Loop 流式测试覆盖 delta 规范化、完整 answer、成功提交、取消/错误不提交和多线程隔离。
- API/ASGI 测试覆盖事件顺序、唯一终态、HTTP/流内错误、断开、背压和同步契约保留。
- Web UI 静态契约或端到端测试覆盖渐进渲染、停止、partial 状态、无自动同步回退和跨线程保护。
- 运行完整 pytest 回归；未访问的真实 provider 或浏览器场景必须诚实记录为 skipped，不得写成通过。
