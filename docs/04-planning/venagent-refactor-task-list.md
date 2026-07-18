# VenAgent 重构任务清单

> 状态：规划基线已确认，Phase 0 尚未启动  
> 日期：2026-07-18  
> 路线图：[VenAgent 重构路线图](./roadmap.md)  
> 说明：本清单是全量 backlog，不代表一次性实施。每个任务在执行前仍需生成详细 TDD 卡片。

## 任务状态定义

- `BLOCKED`：等待安全处置、依赖授权或前置阶段。
- `READY`：前置依赖满足，可进入详细计划/TDD。
- `PENDING`：已定义但未满足前置依赖。
- `DONE`：实现、验证、审查和文档均完成。

## Phase 0：安全、冻结与基线

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P0-01 | 撤销并轮换 AGI-saber 疑似真实 API 凭据 | P0 | BLOCKED | 账号所有者操作 | 旧凭据不可用；审计调用/计费记录 |
| P0-02 | 扫描两仓库所有 refs 与 Git 历史 | P0 | READY | P0-01 可并行先轮换 | 活动秘密已失效；历史命中已清理，或有经批准且标明剩余风险的阻断/豁免记录 |
| P0-03 | 清理 tracked config/Compose 默认凭据 | P0 | READY | 无 | 跟踪文件只含安全模板 |
| P0-04 | 补齐 local secret ignore 与验证 | P0 | READY | 无 | `config.local.yaml`/`.env*` ignored 且未 tracked |
| P0-05 | 冻结 AGI-saber 行为参考和 ADR | P0 | READY | 无 | 记录 python commit；禁止自动同步 |
| P0-06 | 运行 pytest/compileall/可用 coverage 基线 | P0 | READY | 无 | 命令与真实结果入执行记录 |
| P0-07 | 建立 HTTP/SSE/OpenAPI characterization tests | P0 | PENDING | P0-06 | API/SSE 事件顺序、字段和 OpenAPI schema 固化 |
| P0-08 | 建立 chat/RAG/tool/document 行为 fixtures | P0 | PENDING | P0-06 | 新旧 runtime 可复用同一 fixture |
| P0-09 | 建立启动/降级/性能基线 | P0 | PENDING | P0-06 | 记录 startup、TTFT、RAG/workflow latency |
| P0-10 | LangGraph/MCP 依赖版本 spike | P0 | READY | D-12 已确认；仅限隔离验证 | Python 3.11 与现有栈兼容，给出锁定版本；改 requirements 仍需版本确认 |
| P0-11 | 修复重复 `_save_agent_snapshot` | P1 | PENDING | 先写回归测试 | 仅一处定义，行为不变 |
| P0-12 | UUID run identity 替代秒级 task ID | P0 | PENDING | P0-16 | 并发无碰撞，request/run/thread 区分 |
| P0-13 | 删除文档接口真实语义修复 | P0 | PENDING | 契约确认 | 删除成功必须真实删除/标记；不再虚假成功 |
| P0-14 | 安全错误映射与 CORS 基线 | P0 | PENDING | HTTP characterization | 不回传内部异常；生产默认非通配 CORS |
| P0-15 | 全局取消行为建立缺陷测试 | P0 | PENDING | run identity | 证明当前问题并为 per-run 迁移设基线 |
| P0-16 | 形成并确认关键 ADR 基线 | P0 | READY | D-01/D-03/D-07/D-14 已确认 | 生成 ADR-001/003/004/007/012/013；身份、checkpoint、配置、迁移和目标目录决策可追踪 |

## Phase 1：配置与 Bootstrap

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P1-01 | 定义不可变配置模型 | P0 | PENDING | Phase 0 | schema、类型和秘密字段明确 |
| P1-02 | 实现五层配置深度合并 | P0 | PENDING | P1-01 | 默认→共享→local→env→CLI |
| P1-03 | 配置未知字段/组合/脱敏测试 | P0 | PENDING | P1-02 | fail fast，日志不含秘密 |
| P1-04 | 建立 `src/venagent`、`apps/api` 骨架与 dependency container | P0 | PENDING | P0-16/P1-01 | 依赖显式、可测试；新包不导入 `final`，旧入口只向新包委托 |
| P1-05 | 提取 staged Bootstrapper | P0 | PENDING | P1-04 | 阶段诊断清晰 |
| P1-06 | 迁移 `_bootstrap_concurrent` | P0 | PENDING | P1-05 | agent 构造无启动副作用 |
| P1-07 | FastAPI lifespan 装配/关闭 | P0 | PENDING | P1-05 | 所有资源反序关闭 |
| P1-08 | capability health 与降级模型 | P1 | PENDING | P1-05 | 无外部设施时无关功能可用 |
| P1-09 | 兼容 `APIConfig/build_deps` | P1 | PENDING | P1-02/P1-05 | 旧调用和测试可过渡 |
| P1-10 | 启动/关闭/降级集成测试 | P0 | PENDING | P1-07/P1-08 | 无泄漏、无未关闭 worker |

## Phase 2：Ports、能力目录和授权

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P2-01 | 定义 RAG/Memory/Document Ports | P0 | PENDING | Phase 1 | 上层不依赖具体实现 |
| P2-02 | 定义 Search/Sandbox/LLM Ports | P0 | PENDING | Phase 1 | tool call 统一契约 |
| P2-03 | 定义 Run/Snapshot Ports | P0 | PENDING | P0-16 | checkpoint 与业务状态分离 |
| P2-04 | 建立 local adapters | P0 | PENDING | P2-01/P2-02 | 复用现有底座，行为不改 |
| P2-05 | 定义 CapabilityDescriptor/Call/Result | P0 | PENDING | P2-01/P2-02 | 完整 schema/risk/side-effect |
| P2-06 | 建立 CapabilityCatalog/Broker | P0 | PENDING | P2-05 | catalog 可健康过滤和选择 adapter |
| P2-07 | 实现 AuthorizedToolInvoker | P0 | PENDING | P2-06 | 每次执行重新授权 |
| P2-08 | Run 对象级授权与 tenant 隔离 | P0 | PENDING | P2-07/P2-18 | list/status/resume/cancel/SSE/approval 均校验 owner，拒绝不泄露存在性 |
| P2-09 | Sandbox 安全契约与隔离验收 | P0 | PENDING | P2-07 | 无 secret/Docker socket/宿主路径，网络默认关闭，资源和输出受限 |
| P2-10 | 将 IntentDecision 全字段接入 | P0 | PENDING | P2-06 | graph/prompt/agent/memory/recovery 生效 |
| P2-11 | 去除 IntentPolicy 对 legacy router 的直接依赖 | P1 | PENDING | P2-10 + parity tests | deterministic fallback 独立 |
| P2-12 | 建立 canonical preset roles | P0 | PENDING | P2-05 | research/doc_qa/synthesis/ops |
| P2-13 | 结构化 PresetContract | P0 | PENDING | P2-12 | schema、权限、memory、retry 可执行 |
| P2-14 | PresetContext 替代完整 agent 注入 | P0 | PENDING | P2-07/P2-13 | preset 无 service locator 穿透 |
| P2-15 | planner + executor 双重权限测试 | P0 | PENDING | P2-07/P2-14 | 默认拒绝、负面场景完整 |
| P2-16 | 架构依赖测试 | P1 | PENDING | P2-14 | preset/graph 不导入具体 repo/RAG |
| P2-17 | 自定义 Agent 注册与发现 | P0 | PENDING | P2-12/P2-13 | 新角色注册后无需改主流程即可被 catalog 和编排发现 |
| P2-18 | 实现业务 Run/Snapshot Repository 与 schema 迁移 | P0 | PENDING | P1-07/P2-03 | `agent_runs`/snapshot 与 checkpoint 分表；tenant/owner 过滤、向后兼容迁移和回滚路径可验证 |

## Phase 3：真实 LangGraph 只读切片

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P3-01 | 添加锁定 LangGraph/checkpoint 依赖 | P0 | BLOCKED | 用户批准 + P0-10 | requirements 固定版本 |
| P3-02 | 删除/更名本地同名兼容壳 | P0 | PENDING | P3-01 | 不再 import shadowing |
| P3-03 | 定义版本化 GraphState | P0 | PENDING | P2 contracts | 全部可序列化，reducer 明确 |
| P3-04 | 定义 RuntimeEvent | P0 | PENDING | SSE characterization | 与框架 chunk 解耦 |
| P3-05 | 建立静态主图 | P0 | PENDING | P3-03 | profile 条件路由稳定 |
| P3-06 | 实现 clarify 节点 | P0 | PENDING | P3-05 | 低置信请求不再普通 chat |
| P3-07 | 迁移 default_chat | P0 | PENDING | P3-05 | HTTP/SSE 兼容 |
| P3-08 | 迁移 knowledge_answer | P0 | PENDING | P3-05/P2-01 | RAG/降级兼容 |
| P3-09 | 官方内存 saver 单测 | P0 | PENDING | P3-05 | thread 隔离/连续执行 |
| P3-10 | 官方 PostgreSQL saver provider | P0 | PENDING | P3-01/P1 lifespan | 独立生命周期和 schema |
| P3-11 | 重启恢复集成测试 | P0 | PENDING | P3-10 | 真正跨进程恢复 |
| P3-12 | per-profile runtime flag | P0 | PENDING | P3-07/P3-08 | 可即时回旧路径 |
| P3-13 | 只读 shadow comparison | P1 | PENDING | P3-12 | chat/RAG parity |
| P3-14 | SSE RuntimeEvent adapter | P0 | PENDING | P3-04 | 事件顺序/单例/ID 保持 |

## Phase 4：工具、Workflow 与 AgentTeam

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P4-01 | 迁移 single_tool | P0 | PENDING | Phase 3/P2-07 | executor 重新授权 |
| P4-02 | dynamic plan 状态化 | P0 | PENDING | P3-03 | plan 可 checkpoint |
| P4-03 | scheduler/fan-out 子图 | P0 | PENDING | P4-02 | 有界并行、确定性 reducer |
| P4-04 | 错误分类与 retry policy | P0 | PENDING | P4-03 | 只重试临时/幂等失败 |
| P4-05 | race group 分支级语义 | P0 | PENDING | P4-03 | loser 不取消全 run |
| P4-06 | interrupt/Command 审批恢复 | P0 | PENDING | P3 checkpoint | 确认/拒绝/重复 resume 覆盖 |
| P4-07 | per-run governance/cancel | P0 | PENDING | P0-12/P2-08/P2-18 | 并发 run 隔离，状态持久化并可按 owner 查询 |
| P4-08 | 迁移 research | P0 | PENDING | P2-12/P2-13/P2-15/P4-03 | 只读权限 |
| P4-09 | 新增 doc_qa | P0 | PENDING | P2-12/P2-13/P2-15/P4-03 | 只读 document/RAG |
| P4-10 | 迁移 synthesis variants | P1 | PENDING | P4-03 | draft/review 合约化 |
| P4-11 | 迁移 ops/persist_document | P0 | PENDING | P4-06 | 副作用审批/幂等 |
| P4-12 | document workflow 迁移 | P0 | PENDING | P4-08..11 | 现有用户行为兼容 |
| P4-13 | 副作用幂等键 | P0 | PENDING | P2-03 | document/memory/event 不重复 |
| P4-14 | crash matrix 测试 | P0 | PENDING | P4-13 | 节点前后崩溃均可恢复 |
| P4-15 | 恢复后的 SSE 去重 | P1 | PENDING | P4-06/P4-13 | 不重复已确认业务事件 |
| P4-16 | 固定 memory/event 后置节点 | P0 | PENDING | P3-05/P4-13 | 记忆写入和事件通知由图节点执行，恢复时幂等 |

## Phase 5：真实 MCP Adapters

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P5-01 | 添加锁定 MCP SDK 依赖 | P0 | BLOCKED | 用户批准 + P0-10 | 固定已发布版本 |
| P5-02 | MCP endpoint 配置/registry | P0 | PENDING | Phase 1 | 仅受控 server ID |
| P5-03 | stdio client lifecycle | P1 | PENDING | P5-01/P5-02 | 固定 command allowlist |
| P5-04 | Streamable HTTP lifecycle | P0 | PENDING | P5-01/P5-02 | session 初始化/关闭/重连 |
| P5-05 | initialize/list_tools/catalog cache | P0 | PENDING | P5-04 | handshake 后才可见 |
| P5-06 | call_tool/result normalizer | P0 | PENDING | P5-05 | schema/structured/isError 保留 |
| P5-07 | timeout/retry/size/concurrency | P0 | PENDING | P5-04/P5-06 | 资源受限、错误明确 |
| P5-08 | auth reference 与日志脱敏 | P0 | PENDING | P5-02 | 凭据不进模型/日志 |
| P5-09 | SSRF/redirect/DNS/egress policy | P0 | PENDING | P5-02/P5-04 | 私网/metadata/重绑定阻断 |
| P5-10 | 必做 MCP server adapters | P0 | PENDING | P5-01/P2 Ports | RAG、memory、document 与外部工具四类均可标准发现/调用；副作用受审批 |
| P5-11 | `/api/tools/mcp` 兼容 registry service | P0 | PENDING | P5-02/P5-05 | 不再占位，不允许匿名任意 URL |
| P5-12 | local/MCP adapter 切换 | P0 | PENDING | P5-06/P2-06 | 上层无代码变化 |
| P5-13 | exec_command 保持 sandbox/approval | P0 | PENDING | P5-06/P4-06/P2-09 | MCP 不降低权限；无 secret/宿主路径/Docker socket/未授权网络；审批不可跨主体重放 |
| P5-14 | MCP conformance/integration/security tests | P0 | PENDING | P5-03..13 | 协议与安全门禁完整 |
| P5-15 | 移除普通 HTTP `new_mcp_tool` shim | P1 | PENDING | P5-11/P5-12 | 无生产调用方 |
| P5-16 | 基础工具 MCP 契约兼容 | P0 | PENDING | P5-06/P5-10/P5-13 | time/weather/exec 名称、schema、响应和审批语义保持兼容 |

## Phase 6：默认切换与清理

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P6-01 | 所有 profile 默认 LangGraph | P0 | PENDING | Phase 3/4 | 主路径完成 |
| P6-02 | UnifiedAgent 收缩为 façade | P0 | PENDING | P6-01 | 只委托 application |
| P6-03 | Handler routes/schema 拆分 | P1 | PENDING | P6-02 | 每文件职责聚焦；OpenAPI 与 Phase 0 schema 无非预期差异 |
| P6-04 | 移除 Handler 内部穿透 | P0 | PENDING | P6-02/P6-03 | 只依赖用例接口 |
| P6-05 | 删除 legacy router/runtime/shim | P0 | PENDING | 稳定发布周期 | 无生产引用 |
| P6-06 | 删除旧 alias/flags/dead code | P1 | PENDING | P6-05 | 静态分析和测试通过 |
| P6-07 | 完整性能/兼容/安全门禁 | P0 | PENDING | P6-01..06 | 无允许外回归 |
| P6-08 | 更新 codemap/API/ADR/文档 | P1 | PENDING | P6-05 | 文档与源码一致 |
| P6-09 | 切换 canonical `apps/ + src/ + tests/ + config/ + deploy/` 目录入口 | P0 | PENDING | P1-04/P6-01..04 | 新入口可独立运行；`final` 仅为单向兼容壳，新包不反向依赖旧目录 |

## Phase 7：交付

| ID | 任务 | 优先级 | 状态 | 依赖 | 验收摘要 |
|---|---|---|---|---|---|
| P7-01 | 全量测试与适用检查 | P0 | PENDING | Phase 6 | 命令/结果完整记录 |
| P7-02 | 通用 + Python + FastAPI 审查 | P0 | PENDING | P7-01 | 无 CRITICAL/HIGH |
| P7-03 | 安全审查 | P0 | PENDING | P7-01 | secrets/MCP/sandbox/API 通过 |
| P7-04 | E2E/关键用户路径与 OpenAPI 验证 | P0 | PENDING | P7-01 | chat/RAG/tool/document/resume 与公开 schema 兼容 |
| P7-05 | 更新变更日志和发布说明 | P1 | PENDING | P7-01..04 | 交付内容和风险透明 |
| P7-06 | 提交/推送/PR | P1 | BLOCKED | 用户明确授权 | 遵循 Git 工作流 |
| P7-07 | 删除 `final` 兼容目录 | P0 | PENDING | P6-09 + D-10 稳定发布窗口 | 无生产/测试/部署引用；旧 run 已完成或有迁移策略；回滚使用稳定制品 |

## 下一步

整体路线已经确认。后续收到明确的 Phase 0 执行指令后，只启动 Phase 0；Phase 0 完成并评审通过前，不进入 Phase 1，也不把 LangGraph/MCP 依赖加入生产 requirements。
