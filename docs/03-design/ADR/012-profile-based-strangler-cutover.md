# ADR-012: 按 execution profile 采用渐进式切换

## 状态

已接受

## 背景

VenAgent 当前包含自研 graph/runtime、HTTP/SSE 兼容逻辑和多种执行路径。一次性替换全部运行时会扩大回归面，也会让副作用路径难以回滚。

## 备选方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| 一次性切换全部 profile | 最快结束双轨 | 回归范围大，难以定位和回滚 |
| 长期 shadow 执行新旧副作用图 | 可观察差异 | 可能重复副作用，审计和一致性风险高 |
| 按 profile 逐步切换，先只读后副作用 | 风险可控，保留明确回滚点 | 需要 profile flag、parity tests 和兼容窗口 |

## 结论

使用 strangler 模式按 execution profile 迁移：Phase 0 固化行为基线；先迁移 chat/RAG/clarify 等只读路径，再迁移工具、workflow 和 AgentTeam 副作用路径。新旧路径不得同时执行未隔离的副作用。新路径全量默认后保留一个稳定发布周期，再删除 legacy runtime。

## 后果

- 每个切换都必须有 characterization/parity 测试和即时回滚开关。
- SSE 外部契约保持稳定，内部 runtime event 与框架 chunk 解耦。
- legacy 清理只能在稳定窗口和生产引用清零后进行。
