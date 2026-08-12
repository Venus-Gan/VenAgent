# 基础设施启动报告完整目标规格

## 1. 能力定位

VenAgent SHALL 在 application lifespan 中聚合真实装配和检查过的基础设施状态，以安全自然中文向操作者说明 durable/temporary运行能力，并让启动日志与 `/health` 共享同一事实来源。报告不得连接、迁移、重试或为未来模块伪造状态。

## 2. 统一状态

每个状态至少包含稳定 `component`、`ready|degraded|disabled|failed`、`reason_code`、预定义中文 `operator_message`、是否启动必需及安全的 capability影响。机器逻辑读取枚举/code，不解析中文。

文案和结构化字段不得包含密码、token、Cookie、完整连接串、用户名、消息、Prompt、工具参数、数据库原始异常或栈。

## 3. 当前真实组件

- PostgreSQL业务存储与官方 LangGraph checkpointer作为实际装配结果报告；可分别表达连接/schema/checkpointer状态，但不得重复宣称不一致模式。
- AgentRun scheduler/worker只有在后台任务真实启动并可领取时报告 ready；temporary单进程执行仍可报告其受限能力，不能宣称跨进程恢复。
- 前端生产构建只有在实际存在且 FastAPI成功挂载时报告可用；Vite开发形态不伪装成生产静态构建。
- 后续 memory/vector/tool/sandbox/RAG组件只有对应模块真实装配后才加入；不得在本 change提前增加占位状态。

## 4. Durable 与 temporary 选择

- PostgreSQL已配置、可连接、目标 schema有效、checkpointer可用且持久认证配置安全时，状态为 durable/ready，承诺正式 conversation/message/run/checkpoint可在重启后恢复。
- 未配置 PostgreSQL或连接失败时，进程 MAY 以 temporary anonymous mode启动，reason分别稳定表达 not configured/unavailable，说明重启丢失。
- 已连接但 schema缺失、旧版、更新版或不连续时，普通启动不得执行 DDL或读取旧数据；durable失败关闭并以 `persistence_schema_incompatible` 一类稳定 code进入 temporary anonymous mode。
- 持久认证秘密不安全时 durable身份不可用，使用稳定 reason；不得以临时 JWT访问持久 owner数据。
- durable运行中依赖失败不得热切换到第二份内存 owner/run；停止新领取并 fail closed，健康状态反映运行时退化/失败。

## 5. 启动顺序与报告

- composition root显式收集 adapter状态、完成 schema只读验证、reconciler与 scheduler启动，再形成一份不可变 StartupReport。
- 通用报告器只遍历统一状态、选择日志级别和计算汇总，不按具体组件写条件分支或执行副作用。
- 每个 lifespan只输出一次完整报告：ready/disabled为 INFO、degraded为 WARNING、failed为 ERROR，随后输出计数与整体 mode摘要。
- `python -m venagent` 默认显示 VenAgent INFO，不全局提升第三方 INFO。关闭 lifespan时明确停止 scheduler/heartbeat/观察 hub并释放 pool。

## 6. 健康接口

- `GET /health` 保持 HTTP 200的状态快照语义，至少返回 mode、整体 status、基础设施组件、`anonymous_chat`、`account_identity`、`conversation_persistence`、`run_execution`、`restart_recovery`、前端构建能力与稳定 reason codes。
- temporary下 anonymous chat/run可用，但 conversation persistence/restart recovery/account identity不可用；durable ready时相应能力可用。
- `/health` 与启动日志来自同一聚合事实，不通过文案反推字段；启动快照不冒充持续深度探测或 readiness保证。
- 运行期 durable故障可由受控状态更新反映，但不得因此创建第二个 runtime或热迁移数据。

## 7. 失败与安全边界

- 必需组件 failed是否拒绝启动由 bootstrap显式策略决定，报告器不改变生命周期。
- schema不兼容、reconciler失败、scheduler未启动或静态构建缺失使用不同稳定 reason和能力影响，不用一个“数据库错误”掩盖。
- 原始异常只在受保护诊断链中处理，用户响应与默认日志只出现安全 code/文案。
- 非显然的模式选择、无热切换和 lifespan单次报告在实现中添加简洁原因注释。

## 8. 验收

- 覆盖未配置、连接失败、目标 schema ready、旧/新/不连续 schema、checkpointer失败、认证配置失败、scheduler启动失败和前端构建缺失。
- 证明普通启动在 schema不兼容时零 DDL、零旧业务读取，temporary匿名路径可用且健康字段准确。
- 证明 durable运行故障不会创建 memory副本或领取新 run，恢复后必须重新验证 claim。
- 证明日志与 health字段一致、一次 lifespan只报告一次、秘密/原始异常不泄露、第三方 INFO不被全局放开。
