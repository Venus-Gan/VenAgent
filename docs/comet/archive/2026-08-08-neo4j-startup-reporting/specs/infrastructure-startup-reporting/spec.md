# 基础设施启动报告完整目标规格

## 1. 能力定位

VenAgent SHALL 在 application lifespan 中聚合真实装配和检查过的基础设施状态，以安全自然中文向操作者说明 durable/temporary 运行能力，并让启动日志与 `/health` 共享同一事实来源。报告不得连接、迁移、重试或为未来模块伪造状态。

## 2. 统一状态

每个状态至少包含稳定 `component`、`ready|degraded|disabled|failed`、`reason_code`、预定义中文 `operator_message`、是否启动必需及安全的 capability 影响。机器逻辑读取枚举/code，不解析中文。

文案和结构化字段不得包含密码、token、Cookie、完整连接串、用户名、消息、Prompt、工具参数、数据库原始异常或栈。

PostgreSQL、Neo4j 等基础设施 SHALL 与 GraphMemory、长期记忆写入等应用能力使用不同 component 和 reason code；基础设施连接/schema 状态不得由能力文案反推，能力降级也不得改写已确认的启动基础设施快照。

## 3. 当前真实组件

- PostgreSQL 业务存储与官方 LangGraph checkpointer 作为实际装配结果报告；可分别表达连接/schema/checkpointer 状态，但不得重复宣称不一致模式。
- Neo4j 作为独立基础设施报告，状态由 platform runtime 在 driver 创建、连接和 schema 校验后确认；它与 `memory-graph-g1` GraphMemory 能力分别报告，不得合并成同一个组件。
- AgentRun scheduler/worker 只有在后台任务真实启动并可领取时报告 ready；temporary 单进程执行仍可报告其受限能力，不能宣称跨进程恢复。
- 前端生产构建只有在实际存在且 FastAPI 成功挂载时报告可用；Vite 开发形态不伪装成生产静态构建。
- 后续 memory/vector/tool/sandbox/RAG 组件只有对应模块真实装配后才加入；不得提前增加占位状态。

Neo4j SHALL 至少稳定区分 ready、not configured、durable identity required、invalid configuration、driver unavailable、connecting 与 connection/schema unavailable。ready 文案说明连接正常且图 schema 与当前版本兼容；错误文案只暴露安全 reason，不泄露连接或驱动细节。

## 4. Durable 与 temporary 选择

- PostgreSQL 已配置、可连接、目标 schema 有效、checkpointer 可用且持久认证配置安全时，状态为 durable/ready，承诺正式 conversation/message/run/checkpoint 可在重启后恢复。
- 未配置 PostgreSQL 或连接失败时，进程 MAY 以 temporary anonymous mode 启动，reason 分别稳定表达 not configured/unavailable，说明重启丢失。
- 已连接但 schema 缺失、旧版、更新版或不连续时，普通启动不得执行 DDL 或读取旧数据；durable 失败关闭并以 `persistence_schema_incompatible` 一类稳定 code 进入 temporary anonymous mode。
- 持久认证秘密不安全时 durable 身份不可用，使用稳定 reason；不得以临时 JWT 访问持久 owner 数据。
- durable 运行中依赖失败不得热切换到第二份内存 owner/run；停止新领取并 fail closed，健康状态反映运行时退化/失败。
- Neo4j 未配置、配置无效、驱动不可用、连接失败或 schema 不兼容不得改变 PostgreSQL durable mode；GraphMemory 按既有契约禁用或降级，普通长期事实保持可用。

## 5. 启动顺序与报告

- composition root 显式收集 adapter 状态、完成 schema 只读验证、reconciler 与 scheduler 启动，再形成一份不可变 StartupReport。
- 通用报告器只遍历统一状态、选择日志级别和计算汇总，不按具体组件写条件分支或执行副作用。
- 启动报告的稳定顺序为 PostgreSQL、Neo4j、具体记忆能力及其他已装配组件；Neo4j 必须位于 PostgreSQL 之后和第一项记忆能力之前。
- 每个 lifespan 只输出一次完整报告：ready/disabled 为 INFO、degraded 为 WARNING、failed 为 ERROR，随后输出计数与整体 mode 摘要。
- `python -m venagent` 默认显示 VenAgent INFO，不全局提升第三方 INFO。关闭 lifespan 时明确停止 scheduler/heartbeat/观察 hub 并释放 pool。
- `MemoryCapabilityRegistry` 的 `healthy -> recovering -> healthy` 启动握手继续表示 GraphMemory 从 durable 初始能力进入 Neo4j connecting、再完成连接/schema 校验的正常状态过程；该事件不替代最终 Neo4j 基础设施报告。

## 6. 健康接口

- `GET /health` 保持 HTTP 200 的状态快照语义，至少返回 mode、整体 status、PostgreSQL 与 Neo4j 基础设施组件、`anonymous_chat`、`account_identity`、`conversation_persistence`、`run_execution`、`restart_recovery`、前端构建能力与稳定 reason codes。
- `infrastructure.neo4j` SHALL 与启动日志使用同一 Neo4j runtime 状态，至少提供安全 `status`、统一 `state` 和稳定 `reason_code`；不得通过 GraphMemory 能力文案反推。
- temporary 下 anonymous chat/run 可用，但 conversation persistence/restart recovery/account identity 不可用；durable ready 时相应能力可用。
- `/health` 与启动日志来自同一聚合事实，不通过文案反推字段；启动快照不冒充持续深度探测或 readiness 保证。
- 运行期 durable 故障可由受控状态更新反映，但不得因此创建第二个 runtime 或热迁移数据。

## 7. 失败与安全边界

- 必需组件 failed 是否拒绝启动由 bootstrap 显式策略决定，报告器不改变生命周期。
- schema 不兼容、reconciler 失败、scheduler 未启动或静态构建缺失使用不同稳定 reason 和能力影响，不用一个“数据库错误”掩盖。
- Neo4j 基础设施不可用与 GraphMemory 能力不可用分别报告，但不得重复输出原始异常或伪装成两个独立根因。
- 原始异常只在受保护诊断链中处理，用户响应与默认日志只出现安全 code/文案。
- 非显然的模式选择、无热切换和 lifespan 单次报告在实现中添加简洁原因注释。

## 8. 验收

- 覆盖未配置、连接失败、目标 schema ready、旧/新/不连续 schema、checkpointer 失败、认证配置失败、scheduler 启动失败和前端构建缺失。
- 覆盖 Neo4j ready、not configured、durable identity required、invalid configuration、driver unavailable、connection/schema unavailable，并证明 GraphMemory 能力状态与 Neo4j 基础设施状态职责分离。
- 证明健康 PostgreSQL/Neo4j 下启动日志按 PostgreSQL → Neo4j → 具体记忆能力输出，汇总计数包含 Neo4j，且 `/health` 使用同一 Neo4j 状态。
- 证明普通启动在 schema 不兼容时零 DDL、零旧业务读取，temporary 匿名路径可用且健康字段准确。
- 证明 durable 运行故障不会创建 memory 副本或领取新 run，恢复后必须重新验证 claim。
- 证明日志与 health 字段一致、一次 lifespan 只报告一次、秘密/原始异常不泄露、第三方 INFO 不被全局放开。
