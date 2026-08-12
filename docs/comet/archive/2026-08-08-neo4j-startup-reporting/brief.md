# Outcome

让启动日志和 `/health` 将 Neo4j 作为独立基础设施显示，并固定排在 PostgreSQL 之后、具体记忆能力之前，使操作者能区分数据库/图存储连接状态与 GraphMemory 等应用能力状态。

# Scope

- Neo4j platform runtime 维护自身稳定的基础设施状态，包括 ready、not configured、durable identity required、invalid configuration、driver unavailable、connecting、connection/schema unavailable。
- application startup report 固定按 PostgreSQL、Neo4j、具体记忆能力的顺序输出。
- Neo4j ready 文案明确说明连接正常且图 schema 与当前版本兼容；不可用、未配置和被 durable identity 阻止时使用对应安全中文文案与稳定 reason code。
- `/health` 增加 `infrastructure.neo4j`，与启动日志消费同一个 Neo4j runtime 状态。
- 增加启动顺序、Neo4j 状态映射、日志级别、health 一致性和秘密不泄露测试。

# Non-goals

- 不改变 `memory-graph-g1` 等具体能力的状态、文案、降级规则或排序。
- 不改变已确认正常的 `healthy -> recovering -> healthy` 能力状态事件及其现有日志行为。
- 不改变 Neo4j 连接、schema 校验、migration、查询、重试、GraphMemory 召回或 PostgreSQL durable 选择逻辑。
- 不新增前端表面，不修改数据库 schema、环境变量或 Compose 服务。

# Acceptance examples

- 给定 PostgreSQL 与 Neo4j 均连接且 schema 兼容，启动日志依次包含 PostgreSQL ready、Neo4j ready、四项记忆能力，汇总为 6 项可用；Neo4j 文案位于 PostgreSQL 之后和第一项记忆能力之前。
- 给定 Neo4j 未配置，启动报告与 `/health` 将 Neo4j 标记为 disabled/not configured，GraphMemory 能力仍按既有规则 disabled，二者不混为一个组件。
- 给定 Neo4j 连接或 schema 校验失败，Neo4j 基础设施与 GraphMemory 能力均为 degraded，但分别使用基础设施和能力 reason code，PostgreSQL durable 与普通长期事实保持可用。
- 给定运行期具体记忆能力随后发生状态变化，Neo4j 启动基础设施快照不从能力文案反推或被错误改写。

# Constraints and invariants

- startup report 与 `/health` 必须共享 Neo4j runtime 已确认的状态，不在报告阶段重新连接或探测。
- 文案与结构化字段不得包含 URI、用户名、密码、数据库原始异常或栈。
- 通用报告器继续只遍历统一状态，不新增按 Neo4j 名称分支。
- `infra/platform/neo4j/runtime.py` 只拥有 driver 生命周期与基础设施状态，不吸收 GraphMemory 业务规则。
- 保持 feature service 不依赖具体 adapter、HTTP 层不拥有基础设施事实。

# Decisions

- 用户确认 Neo4j 必须作为独立基础设施信息出现，位置固定在 PostgreSQL 之后、具体记忆能力之前。
- `healthy -> recovering -> healthy` 是 Neo4j 启动握手的正常能力状态变化，本 change 保持其既有日志行为，不将其当作故障修复。
- Neo4j 基础设施状态由 `Neo4jRuntime` 持有；GraphMemory 能力继续由 `MemoryCapabilityRegistry` 持有，避免把连接/schema 与应用能力混为同一事实。
- 用户确认不重命名 `GraphMemory：事实图与一跳召回` 或 `关联图谱召回：完整 turn 与派生摘要`，并授权按当前范围推进 change。

# Open questions

无。

# Verification expectations

- 运行 startup reporting、配置、memory/Neo4j runtime 定向 pytest。
- 使用健康本地 PostgreSQL/Neo4j 执行真实 application lifespan，记录日志顺序、汇总计数与 `/health` Neo4j 状态。
- 运行相关 Ruff、compileall、完整根 pytest；既有无关失败如实记录。
- 运行 Comet 内置文本检查并复核日志不泄露秘密。
