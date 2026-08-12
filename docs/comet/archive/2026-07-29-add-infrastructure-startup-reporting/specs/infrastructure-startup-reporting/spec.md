# 基础设施启动报告完整目标规格

## 1. 能力定位

VenAgent SHALL 在应用启动期间将真实基础设施初始化结果聚合为统一报告，并以自然中文向操作者说明各组件状态和整体运行模式。该报告同时保留稳定的机器可读字段，供启动日志与健康接口共享事实来源。

本能力 SHALL 只报告已经由当前运行时真实装配和检查的基础设施，不得为未来模块预造连接、状态或目录。

## 2. 状态契约

每个基础设施启动结果 SHALL 使用不可变统一状态表示，至少包含：

- 稳定组件标识 `component`；
- `ready|degraded|disabled|failed` 状态；
- 稳定 `reason_code`；
- 预定义、无秘密的中文 `operator_message`；
- 该依赖是否为启动必需的事实。

机器逻辑 SHALL 只读取状态和 reason code，不得解析自然语言。运维文案 SHALL 描述实际能力影响，不得包含密码、token、完整连接串、原始异常或其他秘密。

## 3. 聚合与扩展

composition root SHALL 显式收集各 adapter 返回的基础设施状态并形成一份启动报告。通用报告函数 SHALL 只遍历统一状态、选择日志级别、输出安全文案并计算汇总，不得按 PostgreSQL、Milvus、Kafka 或其他具体组件编写条件分支。

新增基础设施时，开发者 SHALL 只需让对应 adapter 提供统一状态并在 composition root 中显式加入报告；不得依赖模块导入副作用、自动发现或全局可变注册表。

## 4. 自然语言日志

应用 lifespan 完成启动前 SHALL 输出一次启动报告。每个组件 SHALL 有一条可独立阅读的自然中文日志，并附带 `component`、`state`、`reason_code` 结构化字段；随后 SHALL 输出可用、降级、未启用和失败数量及整体运行模式的自然语言汇总。

状态到默认日志级别的映射 SHALL 为：

- `ready`：INFO；
- `disabled`：INFO；
- `degraded`：WARNING；
- `failed`：ERROR。

单个应用进程的一次 lifespan SHALL 只输出一次完整报告。标准 `python -m venagent` 入口 SHALL 默认显示 `venagent` 命名空间的 INFO 日志，同时不得因此把全部第三方库 INFO 日志提升到控制台。

## 5. PostgreSQL 行为

当前 PostgreSQL persistence adapter SHALL 提供统一状态，并保持既有 durable/temporary 选择：

- 未配置 PostgreSQL时，状态 SHALL 为 degraded，reason code 为 `postgresql_not_configured`，自然语言说明使用进程内存且重启后上下文失效；服务继续启动。
- PostgreSQL 可连接且 schema 有效时，状态 SHALL 为 ready，reason code 为 `postgresql_ready`，自然语言说明对话可在重启后恢复；服务以 durable 模式启动。
- PostgreSQL 连接失败时，状态 SHALL 为 degraded，reason code 为 `postgresql_unavailable`，自然语言说明连接不可用并已降级；服务继续启动。
- PostgreSQL 已连接但 schema 不可用时，状态 SHALL 为 degraded，reason code 为 `persistence_schema_unavailable`，自然语言说明 schema 不可用并已降级；普通启动不得执行 DDL。
- 持久认证配置不安全导致 temporary 模式时，状态 SHALL 使用稳定 reason code 和安全自然语言说明账号能力不可用。

## 6. 健康接口一致性

启动日志与 `GET /health` SHALL 来自同一份已聚合状态事实。`GET /health` SHALL 保持 HTTP 200、顶层 `status: ok`、现有 mode、PostgreSQL、capabilities 和 reason code 契约；自然语言展示不得改变已有客户端字段。

启动报告是启动快照，不宣称持续探测运行中依赖，也不新增无真实依赖计算的 readiness 端点。

## 7. 安全与失败边界

报告函数 SHALL NOT 连接、重试、迁移或修改任何基础设施。adapter 捕获的原始异常 SHALL NOT 进入操作者文案或结构化字段。必需依赖失败是否拒绝启动 SHALL 由 bootstrap 的既有应用策略决定，报告函数不得自行改变生命周期结果。

## 8. 可维护性与注释

实现 SHALL 在统一状态契约、聚合边界和 lifespan 单次输出等非显然位置添加简洁注释，说明职责和不变量。注释 SHALL NOT 逐行复述显而易见的赋值或循环。

## 9. 验收基线

实现 SHALL 证明：

- 未配置 PostgreSQL时服务成功降级启动，并输出自然语言和一致 `/health`；
- 可用且已迁移 PostgreSQL时服务 durable 启动，并输出自然语言和一致 `/health`；
- 连接失败与 schema 不可用时使用 WARNING 安全降级，且不泄露连接信息；
- 报告在一次 lifespan 中只输出一次，并正确汇总所有统一状态；
- 测试加入模拟基础设施状态时无需修改通用报告函数；
- Uvicorn 和 VenAgent INFO 日志均可见，第三方 INFO 不会被全局放开；
- 现有后端测试保持通过。
