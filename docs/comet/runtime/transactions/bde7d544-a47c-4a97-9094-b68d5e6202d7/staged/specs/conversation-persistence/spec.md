# Conversation Persistence 完整目标规格

## 1. 目标

VenAgent SHALL 使用业务数据库持久化 owner、conversation、正式 message、AgentRun、RunGrant、claim/lease 与幂等请求，使用官方 LangGraph checkpointer 持久化每个 run 的图状态。两类存储通过稳定 `run_id` 关联，但拥有独立事务边界，并由显式 reconciler 幂等对账。

## 2. 新 schema 与旧版本边界

- 本 capability 的 canonical schema 只支持新的 `ConversationMessage + AgentRun + RunGrant + per-run checkpoint` 模型；旧 `conversation_threads`、`conversation_turns`、history/checkpoint version 和 conversation-scoped checkpoint 不兼容。
- 项目当前允许开发期重建 schema。迁移命令 SHALL 显式创建目标版本；不得从旧消息、run 或 checkpoint 自动转换、双写或保留兼容视图。
- 普通应用启动 SHALL 只验证 schema，不执行 DDL。缺表、旧版本、更新版本或 history 不连续时 durable 能力失败关闭并使用稳定 reason code，不得尝试破坏性修复。
- schema history SHALL 记录应用 schema 与官方 checkpointer 版本；业务代码不得读取、修改或依赖 checkpointer 私有物理表。

## 3. 业务持久化约束

- PostgreSQL SHALL 通过外键、check、唯一索引和部分唯一索引保证 owner 隔离、conversation/message/run 关联、状态枚举、幂等请求和每 conversation 单活跃 run。
- assistant message 的 `source_run_id` 与 `reply_to_message_id` SHALL 唯一；succeeded run 必须关联 output message，其他状态不得伪造成功 output。
- RunGrant 必须与 run、owner、conversation 和 authorization epoch 一致；grant 与 run 使用受控生命周期，不把 token、Cookie 或秘密存入业务表。
- claim 至少持久化 `claimed_by`、`claim_token`、`lease_expires_at`、`execution_attempt`；状态与终态更新使用 CAS/fencing，不依赖进程内锁保证正确性。
- 数据库时间是 lease、TTL 和过期判断的权威。业务状态机留在应用服务，不用复杂 trigger 隐藏生命周期逻辑。

## 4. Checkpointer

- durable 模式使用官方 PostgreSQL checkpointer；temporary 模式使用进程内 checkpointer。两者通过同一公开 adapter 接口访问。
- 唯一映射 helper SHALL 把 `run_id` 转为 LangGraph configurable `thread_id`；任何 conversation/HTTP/store 层不得自行拼装该配置。
- retry 创建新的 run/checkpoint；恢复 worker 继续原 run/checkpoint。删除按 run ID 调用公开 delete contract。
- 最终 checkpoint 与业务成功事务之间不使用分布式事务；startup/query/worker recovery/finalizer 通过公开图状态和 AgentRun 幂等对账。
- checkpoint 不保存业务消息、owner session、凭据、完整工具事实或长期记忆；State 只保存恢复图所需字段和稳定引用/摘要。

## 5. Durable 启动与运行故障

- 只有连接、schema、checkpointer 和持久认证配置全部有效时进入 durable mode；此模式承诺正式消息、run 与 checkpoint 可在服务重启后恢复。
- durable 启动 SHALL 在对外接收新 run 前完成：schema 验证、删除/取消恢复、过期 lease 扫描、checkpoint/run 对账和 scheduler 就绪；每个步骤失败使用安全状态，不泄露数据库错误。
- durable 运行中数据库不可用时不得切换到新的内存 owner/store，不得领取新 run、启动新模型或副作用；活动 worker进入进程内 `lease_uncertain` 并等待重新确认。
- 连接恢复后，只有仍持有当前 fencing token 的 worker 才可继续写；已丢失 claim 的 worker 丢弃迟到业务写，由当前 worker 对账。
- 数据库暂时不可用本身不直接把 run 标为 failed；只有达到已批准的无进展恢复预算或确定不可恢复才收敛稳定失败。

## 6. Temporary 模式

- PostgreSQL 未配置、连接失败、schema 不兼容或持久认证配置不可用时，应用 MAY 以明确的 `temporary` anonymous mode 启动；普通启动不得因此改写数据库。
- temporary 使用相同领域服务、run API、SSE、状态机和前端契约，但 owner、conversation、messages、runs、grants、claim 与 checkpoint 仅存在进程内；重启全部丢失且永不迁移到 PostgreSQL。
- temporary 不宣称跨进程 worker 接管或服务重启恢复；单进程内仍必须遵守单活跃、幂等、取消、finalizer 与身份隔离。
- 账号能力在 temporary 不可用；前端和 `/health` 必须明确显示匿名可用、持久化不可用、重启会丢失。运行期不做 durable/temporary 热切换。

## 7. 启动、恢复和删除顺序

- startup reconciler 对 queued、过期 running、waiting、取消请求、终态不变量和 checkpoint 状态分类处理；操作可重复且不得重新执行已成功发布的 run。
- 最终 checkpoint 存在而 run 非终态时恢复 finalizer；业务成功已存在时不重跑模型；active interrupt 投影 waiting；contract mismatch 投影 incompatible。
- conversation/owner 删除先禁止访问和新运行，再请求非终态取消，等待外部事实收敛后删除 messages/runs/grants/checkpoints；单对象失败不把其他对象误标完成。
- 清理任务记录稳定 reason、数量和耗时，不记录用户名、消息、Prompt、凭据、连接串或原始异常。

## 8. Store 边界与事务

- `conversation/` 与 `ownership/` 定义消费方 Protocol；PostgreSQL/内存 adapter 只实现端口，不承载 retry、finalizer、授权或删除策略。
- 初次创建、明确 retry、取消请求、claim、heartbeat、finalizer 和删除标记各自使用明确事务/CAS 边界。
- finalizer 的 assistant insert、run succeeded/output、conversation 时间/标题/TTL 与 claim 清理必须在一个业务事务中；任何失败不得对用户发布 completed。
- 所有 SQL 参数化；分页、锁与并发路径有确定排序，避免无界扫描和死锁顺序漂移。

## 9. 验收

- 在全新隔离 PostgreSQL 上运行显式 migration，证明目标 schema、官方 saver 和重启恢复；旧/新/不连续 schema 的普通启动不执行 DDL并安全降级。
- 并发测试证明单活跃、幂等、claim/fencing、过期接管、旧 worker 迟到写拒绝和 owner running 上限。
- 故障注入覆盖每个 checkpoint/业务事务/通知窗口、数据库抖动、重复 reconciler、删除中断和 cleanup 重试。
- temporary 模式证明相同用户主路径可用、账号不可用、重启丢失、不会污染随后可用的 durable 数据。
- 验证所有 checkpointer 操作只走公开 API，业务测试不依赖 LangGraph 表名或内部列。
