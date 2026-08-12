# Checkpoint 序列化策略完整目标规格

## 目标

VenAgent SHALL 为官方 LangGraph checkpointer 使用集中、显式且最小的 msgpack 类型 allowlist，使异步运行、同步启动校验和显式 migration 对同一 checkpoint 数据采用一致的反序列化安全策略。

## 所有权与复用

- agent runtime SHALL 公开唯一 checkpoint serializer helper，列出当前 `RunState` 实际持久化的 VenAgent dataclass 类型。
- durable 异步 `AsyncPostgresSaver`、启动期同步 `PostgresSaver` schema/checkpoint 校验和 `python -m venagent migrate` 的同步 `PostgresSaver` SHALL 复用该 helper。
- platform 和 migration 不得各自复制 allowlist，不得使用全类型许可，也不得依赖进程环境决定是否发出兼容警告。
- temporary checkpointer 可以保留官方进程内实现，但涉及持久 checkpoint 编解码的测试 SHALL 使用同一策略验证项目自定义类型。

## 安全与兼容

- allowlist SHALL 只包含 VenAgent 当前 checkpoint State 中需要恢复的项目自定义类型；内建安全类型继续由 LangGraph 官方 serializer 管理。
- 未注册的项目自定义 msgpack 类型 SHALL 被拒绝，不能静默退回 permissive 模式或 pickle fallback。
- 现有由当前 RunState 类型写入的 checkpoint SHALL 可继续读取，不修改官方 checkpoint schema、blob 格式或 thread identity。
- 错误和日志不得包含 checkpoint blob、完整 Prompt、数据库连接串或凭据。

## 生命周期

- 普通应用启动仍只校验 schema/checkpoint 兼容性，不执行 DDL。
- migration 仍是唯一执行官方 saver `setup()` 和 VenAgent schema 迁移的入口。
- serializer 变化不得创建第二套 checkpointer、连接池或迁移路径。

## 验收

- 现有 `TaskInput`、`PlanNode`、`Plan`、`NodeOutcome`、`ApprovalItemRef`、`ApprovalWait`、`FinalAnswer` 和 `RunFailure` checkpoint 可在同步与异步 saver 中恢复。
- migration、启动校验和 runtime 恢复不再输出 unregistered msgpack type warning。
- 未列入 allowlist 的项目自定义类型被稳定拒绝。
- 真实 PostgreSQL 的写入、重启恢复、finalizer 幂等、删除和连接池关闭行为保持通过。
