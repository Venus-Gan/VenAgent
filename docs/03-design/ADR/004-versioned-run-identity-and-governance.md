# ADR-004: 使用版本化 run identity 与对象级治理

## 状态

已接受

## 背景

当前任务标识存在秒级 ID 和全局取消语义，无法可靠区分并发执行，也无法为恢复、SSE、审批和跨主体访问控制提供稳定边界。

## 备选方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| 保留秒级 task ID 和全局 current task | 兼容现状 | 并发冲突，取消和授权边界错误 |
| 直接把 checkpoint ID 作为公共 ID | 实现简单 | 暴露框架内部细节，难以做业务授权和迁移 |
| UUID `run_id` + 服务端映射的 `thread_id` | 并发安全，公共契约稳定 | 需要 run repository 和治理层 |

## 结论

公共 API 只接受 UUID `run_id`。服务端维护 `tenant_id`、`principal_id`、`request_id`、`run_id`、内部 `thread_id` 和框架 `checkpoint_id` 的映射。所有 list/status/subscribe/cancel/resume/approval 操作必须按 tenant、principal 和 run 做对象级授权；拒绝响应不得泄露目标是否存在。

## 后果

- 取消必须是 per-run，不再使用 `cancel_all()` 作为业务语义。
- 业务 run 状态、checkpoint、审批证据和 capability audit 必须共享身份绑定。
- 现有 HTTP/SSE 兼容层需要把旧 task 字段迁移或映射到新的 run identity。
