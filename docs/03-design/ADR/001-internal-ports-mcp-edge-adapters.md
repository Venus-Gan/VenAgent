# ADR-001: 使用内部 Ports 与 MCP 边界适配器

## 状态

已接受

## 背景

VenAgent 需要同时支持进程内的 RAG、memory、document、sandbox 等能力，以及外部 MCP 工具。若所有调用都强制经过 MCP transport，会增加序列化、网络故障域、事务边界和测试成本；若上层直接依赖具体实现，又会阻碍本地与 MCP 适配器切换。

## 备选方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| 所有内部调用强制走 MCP | 协议统一 | 延迟、故障域和测试复杂度增加，过早分布式化 |
| 上层直接调用具体后端 | 改动少 | 编排层与存储/transport 强耦合，难以替换 |
| 内部 Ports + 本地/MCP 边界适配器 | 保持进程内类型和事务边界，同时支持协议互操作 | 需要维护稳定 contract 和两类 adapter |

## 结论

采用内部应用 Ports。进程内能力使用本地适配器；外部能力使用真实 MCP client adapter；需要对外暴露的能力使用 MCP server adapter。编排层只依赖稳定能力 contract，不直接依赖数据库、HTTP transport 或 MCP session。

## 后果

- RAG、memory、document、sandbox、LLM、repository 等能力必须定义 Ports 和 capability contract。
- MCP 适配器负责协议、生命周期、认证、超时、大小限制和审计；不能绕过授权执行器。
- 同一能力可以先使用本地 adapter，后续按 profile 切换为 MCP adapter。
