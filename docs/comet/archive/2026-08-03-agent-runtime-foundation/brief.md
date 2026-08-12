# Outcome

将 VenAgent 从“HTTP 连接内执行的一次性 thread/turn AgentLoop”重构为可持久恢复的运行基础：正式消息使用 `ConversationMessage`，每次执行使用可查询的 `AgentRun`，LangGraph checkpoint 按 `run_id` 隔离，SSE 只传输实时观察而不拥有任务生命周期。完成后，发送、后台继续、断线重连、刷新恢复、取消、失败重试和最终回答发布形成一条真实可用的端到端路径，为 M05 记忆、M06 工具和 M07 图编排提供稳定边界。

# Scope

- 以 `Conversation`、`ConversationMessage`、`AgentRun`、`RunGrant` 替换旧 `ThreadRecord`、成对 `TurnRecord`、`ConversationRun` 和进程内权威 run registry；不兼容旧业务数据与 checkpoint。
- 建立 `AgentRunLifecycle`、数据库单活跃约束、原子创建、幂等请求、claim/lease/heartbeat/fencing、取消请求、崩溃对账和幂等 finalizer。
- LangGraph 使用每个 run 独立的 State/checkpoint，唯一 adapter 固定 `thread_id=run_id`；图执行成为权威路径，不再在模型直调后补写 checkpoint。
- 实现新的 conversation/run/query/cancel/retry/SSE API；断连不取消，重连先返回权威 snapshot，SSE 不保存 token delta。
- 前端分离正式消息、run 投影和内存 partial，切换到创建 run 后订阅/轮询的协议，并覆盖桌面与移动端真实交互。
- 保留 M04 的 owner/session 安全事实，引入最小 `RunGrant`，使普通 logout/session 过期不等于取消后台 run，而 owner 删除、安全撤销和 tenant/guest 生命周期失效会阻止继续执行。
- 建立最小 `ProjectionInputCollector`、`ContextProjectionService`、`ContextBlock`、角色级 `ProjectionPolicy`、`TokenCounter` 和 `BudgetReport`，只交付当前单节点回答所需的上下文投影起点。
- 重建 PostgreSQL schema 和内存 adapter，更新 composition root、健康/启动报告、测试、文档与前端生产托管契约。

# Non-goals

- 不兼容、迁移或读取旧 `conversation_threads`、`conversation_turns`、旧 API、旧浏览器缓存或旧 conversation checkpoint；不提供双写、shim、灰度协议或自动导入。
- 不在本 change 实现长期记忆提取/召回、RAG、工具执行、sandbox、OperationGrant、审批决策、Planner、Replanner、子 Agent 或任务内并行。
- 不建设回答分支、重新生成成功回答、回答版本切换、通用 `AgentRunEvent`、token delta 账本、事件溯源、分布式事务、消息队列或通用规则引擎。
- 不把 M05 的过滤器、mode 与槽位编排表钉死；本 change 只定义可扩展的 section/filter 输入输出契约和当前默认策略。
- 不为 M09 的规模化能力预建目录、队列、优先级、运维 UI 或跨进程事件总线。

# Acceptance examples

- 用户发送消息时，服务在一个事务中写入 user message、queued run 和 RunGrant，返回 202；即使尚未连接 SSE，worker 也能领取并执行。
- 用户在生成中刷新页面或关闭浏览器，run 不被取消；重新打开后先查询 snapshot，成功时取得唯一持久化 assistant message，断线期间 token 不要求补放。
- 用户显式取消 running 或 waiting run，持久取消请求先落库；图在安全边界响应，最终为 cancelled，partial 不进入正式历史。
- 模型失败后，最新未完成 user message 可显式 retry；新建 run 和 checkpoint，旧 run 保持原终态。消息之后已有新 user message、run 已成功或权限不再有效时拒绝原地 retry。
- worker 在事务提交后、首次领取前崩溃，queued run 仍可被领取；worker 在 checkpoint 后失联，lease 过期后新 worker 以新的 fencing token 恢复同一 run。
- 最终 checkpoint 成功而业务发布前崩溃，finalizer 重放只创建一条 assistant message；业务事务成功而 SSE 前崩溃，查询返回既有成功结果，不重新调用模型。
- 普通 logout 或 access session 过期后，既有 RunGrant 仍可支持原 run 完成；owner 删除、安全撤销、guest 生命周期失效或授权 epoch 不匹配时恢复失败关闭。
- PostgreSQL 未配置或不可用时，应用仍以 temporary anonymous 模式提供同协议的进程内运行，但明确说明重启丢失；schema 不兼容时普通启动不执行 DDL，也不读取旧数据。
- 真实浏览器在 Vite 代理和 FastAPI 托管生产构建两种形态下完成发送、渐进 token、后台继续、重连、取消、失败重试、终态替换、跨 owner 隔离和 390px 窄屏操作。

# Constraints and invariants

- `conversation_id`、`message_id`、`run_id`、`owner_id` 与 LangGraph adapter 的 `thread_id` 含义分离；业务接口不得暴露或依赖 checkpointer 物理表。
- `ConversationMessage` 只保存正式 user/assistant 消息；失败、取消、等待审批、不兼容和流式 partial 不伪造 assistant message。
- 每个 conversation 同时最多一个 `queued|running|waiting_approval` run；每个 run 只有一条 checkpoint 链；同一 user message 最多一条成功 assistant message。
- 最终 checkpoint 先完成；assistant message、`AgentRun.succeeded`、`output_message_id` 和 conversation 更新时间在同一业务事务原子发布；事务提交后才能宣告 completed。
- 所有生命周期写入经统一状态机、CAS 和 fencing 校验；HTTP route、LangGraph node、scheduler 和 adapter 不得直接越权写终态。
- worker 不代行 owner。运行权限来自绑定单个 run 的最小 RunGrant，秘密、Cookie、JWT、API key 和明文凭据不得进入 RunGrant、AgentRun、State、checkpoint、Prompt 或日志。
- 数据库/claim 不确定时停止新领取和新副作用，已有结果等待对账；不能因暂时基础设施故障直接伪造 failed 或 succeeded。
- temporary 与 durable 使用相同领域/HTTP/前端契约；temporary 不跨进程恢复，durable 才承诺重启恢复。运行期不得在两种 store 间热切换。
- 业务用例不依赖 FastAPI、psycopg 或具体 provider；`infra/` 不承载 use case，`interfaces/http/` 不承载业务事实。
- 所有非显然的不变量、提交顺序、fencing、取消与 partial 边界在实现中添加简洁的“为什么”注释。

# Decisions

- 使用四层模型：持久业务消息 `ConversationMessage`、持久执行生命周期 `AgentRun`、每 run 的 LangGraph State/checkpoint、每次调用生成的 `ContextProjection`；`ActiveRunContext` 仅是进程内临时资源。
- `AgentRun.status` 固定为 `queued|running|waiting_approval|succeeded|failed|cancelled|incompatible`，终态原因使用稳定 code；`retry_eligible` 是查询时动态投影。
- 新 API 采用“创建 run 返回 202，再查询或订阅”，SSE 首个业务事件为 snapshot；不使用连接断开表达取消，不承诺 token replay。
- 不使用 checkpoint 代替 AgentRun、ConversationMessage、RunGrant 或业务事件；也不新增通用事件表。
- 默认调度基线：lease 60 秒、heartbeat 15 秒、poll 2 秒加 jitter、worker 顶层并发 2、owner running 上限 2、连续无进展恢复上限 3；使用数据库时间与 claim token fencing。
- 用户显式 retry 创建新 run，不复活旧 run、不继承旧 checkpoint；只有最新未完成 user message 可重试，成功回答不支持重新生成/分支。
- 普通 logout/session 过期不取消既有 run；owner deleting/deleted、安全撤销、tenant 失效和 guest 生命周期结束使 RunGrant 失效。
- 旧 schema/API/checkpoint/browser cache 全部弃用，开发部署允许重建；普通启动遇到不兼容 schema 失败关闭 durable 能力，不自动破坏性迁移。
- ContextProjection 的基础 section/filter/mode 仅作为后续模块的可修订起点；M05、M06、M07 在各自 Shape 中可以基于证据调整字段、预算与槽位编排，但不得改变四层所有权和安全边界。
- 实施按“领域模型与数据库约束 → 生命周期服务与 scheduler → LangGraph/对账 → HTTP/SSE → 前端 → 删除恢复与启动 → 分层验证”推进；每一步保持可回退到未启用的新协议，禁止半套新旧协议共同对外可用。

# Open questions

- 无。当前 brief 与完整候选规格已于 2026-08-03 获用户确认，可作为 Build 契约。

# Verification expectations

- 领域单元测试覆盖状态转换矩阵、幂等、单活跃、retry eligibility、取消/成功竞态、RunGrant 失效和安全错误映射。
- PostgreSQL 隔离集成测试覆盖全新 schema、约束、claim/lease/fencing、并发领取、重启恢复、finalizer 各崩溃窗口、删除与 orphan/checkpoint 清理；不得把 mock SQL 当成唯一证据。
- LangGraph 测试只使用公开 State/checkpointer API，覆盖 run_id 隔离、checkpoint 恢复、取消检查、runtime contract mismatch、最终答案/失败互斥和幂等 finalization。
- HTTP/SSE 契约测试覆盖 202 创建、query、snapshot、实时 token、无 token replay、轮询回退、断连不取消、取消、retry、401/404/409/429/503 与跨 owner 不泄露。
- 前端单元/组件/E2E 覆盖 messages/runs/partial 分离、迟到事件隔离、刷新恢复、多个失败尝试折叠、终态替换、智能滚动、身份切换和资源清理。
- Verify 必须同时启动真实 Vite 代理形态与 FastAPI 托管的生产构建，通过浏览器人工执行关键路径并检查控制台、网络、重复消息和移动布局；发现问题后修复并重验。
- 运行 Python 全量 pytest、前端 typecheck/build/E2E、compileall、架构依赖扫描和文本卫生检查；外部 PostgreSQL 或浏览器条件不可用时如实记录，不能虚构通过或以纯 mock 替代。
- 安全复核覆盖 owner 隔离、RunGrant 最小权限、session/owner 生命周期、CSRF/Origin/CORS、秘密保护、日志脱敏、输入上限和删除竞态。
