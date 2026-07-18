# ADR-003: 分离 LangGraph checkpoint 与业务 snapshot

## 状态

已接受

## 背景

框架 checkpoint 用于图状态恢复，业务 snapshot 用于用户和运维查看。二者生命周期、索引、升级方式和安全访问边界不同，当前将二者混用会使恢复语义和业务状态难以验证。

## 备选方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| 复用 `task_snapshots` 模拟 checkpoint | 迁移成本低 | 不是真实框架 saver，恢复和升级语义不可靠 |
| 只使用内存 saver | 简单 | 重启后无法恢复 durable workflow |
| 官方 PostgreSQL checkpointer + 独立业务 repository | 恢复语义清晰，职责分离 | 需要两套 schema、生命周期和一致性测试 |

## 结论

生产 durable workflow 使用官方 PostgreSQL checkpointer；业务 `agent_runs`/snapshot 使用独立 repository 和 schema。单元测试使用官方内存 saver。两者都必须继承 tenant、principal、run 绑定，访问前先完成对象级授权。

## 后果

- Phase 0 先固化现有 snapshot 行为，Phase 2/3 再实现两类存储。
- resume、cancel、status、SSE reconnect 和 approval 必须先授权，再解析内部 checkpoint identity。
- PostgreSQL 不可用时，chat 可以降级；需要恢复的 workflow 必须明确拒绝或显式以 non-durable 模式运行。
