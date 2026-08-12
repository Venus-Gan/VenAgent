# Outcome

VenAgent 启动时以自然中文输出真实基础设施状态，并保留稳定的机器可读状态字段。当前 PostgreSQL 的正常、未配置和故障降级结果均可由操作者直接理解；后续新增基础设施只需提供统一状态并在 composition root 显式装配，不修改通用日志报告函数。

# Scope

- 为基础设施启动结果定义不可变、可扩展的统一状态契约和聚合报告。
- 让 PostgreSQL persistence runtime 产生该统一状态，同时保持现有 durable/temporary 行为与 `/health` 契约。
- 配置 `venagent` 日志命名空间，使标准启动入口默认显示应用 `INFO` 日志而不放开全部第三方库日志。
- 在 FastAPI lifespan 启动完成前输出一次逐项自然语言状态和最终汇总。
- 覆盖 PostgreSQL 未配置、正常连接、连接或 schema 故障降级，以及日志脱敏和扩展性。
- 在非显然的状态边界、聚合和生命周期调用处添加简洁代码注释说明职责。

# Non-goals

- 不提前接入或虚构 Milvus、Kafka、Neo4j 等尚未进入当前运行时的基础设施。
- 不增加自动发现、全局注册表、基础类层级、多语言系统、JSON 日志格式或新的 readiness 端点。
- 不改变 PostgreSQL migration、降级启动、能力可用性或 `/health` HTTP 200 语义。
- 不在报告函数中重新探测、连接或修改基础设施。

# Acceptance examples

- PostgreSQL 未配置时，服务成功启动；日志用自然中文说明当前使用进程内存且重启后上下文失效，最终摘要说明以降级模式运行；`/health` 保持 `mode=degraded`、`postgresql.status=not_configured`。
- PostgreSQL 已配置、可连接且 schema 有效时，服务成功启动；日志说明 PostgreSQL 正常且对话可恢复，最终摘要说明 durable 模式；`/health` 保持 `mode=durable`、`postgresql.status=connected`。
- PostgreSQL 已配置但连接失败或 schema 不可用时，服务继续以 temporary 模式启动；对应状态使用 WARNING 自然语言说明故障降级，并保留稳定 reason code。
- 启动报告在单个应用进程的 lifespan 中只输出一次；每个组件日志同时附带 component、state 和 reason_code 结构化字段。
- 日志不包含密码、完整连接串、token 或原始异常文本。
- 新增一个测试用模拟基础设施状态时，通用报告函数无需增加组件专属分支即可输出状态并计入汇总。

# Constraints and invariants

- adapter 只返回事实状态，不得调用通用启动报告函数；bootstrap 是显式装配和聚合入口。
- 自然语言采用预定义的安全运维文案，机器判断只依赖 state 和 reason_code，不解析文案。
- `ready` 和 `disabled` 使用 INFO，`degraded` 使用 WARNING，`failed` 使用 ERROR；整体运行模式仍由现有应用契约决定。
- 启动日志与 `/health` 消费同一份状态事实，不能维护两套独立探测结果。
- `python -m venagent` 保持标准启动入口，Uvicorn 自身日志继续正常输出。
- 注释说明非显然的设计目的，不添加逐行复述代码的无效注释。

# Decisions

- 用户确认采用“统一状态契约 + 一个通用报告函数 + composition root 显式装配”的实现方向。
- 用户要求自然语言输出，并确认未来会增加更多基础设施。
- 用户接受两个主要端到端场景并补充连接/schema 故障降级场景作为完整验收。
- 用户要求编写代码时添加说明作用的注释。
- 当前只实现真实存在的 PostgreSQL 状态；未来扩展不使用自动注册副作用。

# Open questions

无。

# Verification expectations

- 运行相关 pytest，验证状态契约、日志级别、自然语言、汇总、单次输出、脱敏和 `/health` 一致性。
- 运行完整后端 pytest 回归。
- 分别以未配置 PostgreSQL和可用 PostgreSQL 启动后端观察真实控制台输出；若本机数据库条件不可用，必须如实记录跳过并以隔离测试覆盖。
- 验证配置了不可达 PostgreSQL 时服务仍降级启动且日志不泄露连接信息。
