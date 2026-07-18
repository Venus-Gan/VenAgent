# VenAgent 重构最终需求追踪矩阵与决策清单

> 状态：规划基线已确认，Phase 0 进行中
> 审查日期：2026-07-18  
> 需求来源：[VenAgent 重构 PRD](../02-requirements/PRD/venagent-refactor.md)  
> 事实基线：[VenAgent 重构现状审计](../01-research/technical-audit.md)  
> 目标设计：[VenAgent 重构目标架构](../03-design/venagent-refactor-target-architecture.md)  
> 目录设计：[VenAgent 目标目录层次与迁移边界](../03-design/venagent-target-directory-structure.md)  
> 实施路线：[VenAgent 重构路线图](./roadmap.md)  
> 执行清单：[VenAgent 重构任务清单](./venagent-refactor-task-list.md)

## 一、审查结论

PRD 的功能目标、非功能目标和迁移约束均已映射到当前实现、目标设计、实施阶段和验收门禁。用户已于 2026-07-18 接受本文件第六节的全部推荐项，本规划可以作为后续实施基线。该确认不等于已执行外部账号操作、添加生产依赖、清理 Git 历史或启动 Phase 0。

本轮规划的核心结论是：

- 保留 RAG、memory、document、sandbox、repo、infra 与现有 HTTP/SSE 契约；
- 用内部 Ports 隔离实现，通过真实 MCP client/server adapters 实现协议互操作；
- 用官方同步 LangGraph 和独立 PostgreSQL checkpointer 渐进替换自研 runtime；
- 让 IntentPolicy、AgentTeam 权限、run 治理和配置分层从“结构存在”变为“运行时强制执行”；
- 采用 profile-based Strangler，先只读、后副作用，每阶段可验证、可回退；
- AGI-saber 冻结为行为参考，不再作为持续代码上游。

## 二、最终需求追踪矩阵

状态含义：`已完成基础能力` 表示当前实现可保留；`部分完成` 表示已有结构但未满足完整验收；`未完成` 表示需要在路线图中交付。

| ID | PRD 需求 | 当前状态 | 目标设计 | 实施任务 | 最终验收 |
|---|---|---|---|---|---|
| INT-01 | 结合输入、上下文、工具和偏好生成结构化决策 | 部分完成：已有 `IntentSignal/Decision`，上下文和偏好参与不足 | IntentPolicy 接收 capability health、registry、memory/recovery 和用户约束 | P2-10、P2-11、P3-05 | 决策 DTO 字段完整、可审计，策略测试覆盖上下文与偏好 |
| INT-02 | 覆盖对话、知识问答、单工具、工作流、文档处理 | 部分完成：profile 已存在，生产执行仍是旧分派 | 静态主图按 execution profile 条件路由 | P3-05～P3-08、P4-01、P4-12 | 五种 profile 均进入真实图，外部行为兼容 |
| INT-03 | 工具、Agent、memory、recovery scope 被执行 | 部分完成：主要只消费 profile/tool scope | Policy、Preset、部署、用户、审批、健康状态取交集 | P2-06～P2-15 | planner 过滤且 executor 再授权，越权负面测试通过 |
| INT-04 | 低置信意图先澄清 | 部分完成：可判定但仍落入 chat | 专用 clarify 节点 | P3-06 | 低置信请求不会擅自执行工具或工作流 |
| INT-05 | 旧关键词规则被策略层吸收，不再散落 | 部分完成：策略仍直接依赖 legacy router | 确定性规则成为独立 fallback，移除旧 router 依赖 | P2-11、P6-05 | 生产路径无 legacy router 引用，规则 parity 测试通过 |
| MCP-01 | 搜索后端可替换且不绑定服务商 | 部分完成：默认不再强绑 Tavily，但缺统一 adapter | Search Port + local/MCP adapter | P2-02、P2-04、P5-12 | 切换搜索 adapter 不改 graph/preset |
| MCP-02 | RAG、memory、document、外部工具通过 MCP 标准接口暴露 | 未完成：当前是元数据/HTTP 占位 | 内部 Ports + 必做 MCP server adapters | P5-01～P5-15 | 四类能力可 initialize/discover/call，副作用有授权和幂等门禁 |
| MCP-03 | 上层只依赖稳定输入输出，不接触实现 | 部分完成：preset/Handler 仍穿透具体对象 | Capability contract + application Ports | P2-01～P2-07、P2-14、P6-04 | 架构测试禁止 graph/preset/Handler 依赖具体实现 |
| MCP-04 | 时间、天气、命令执行接口兼容 | 已完成基础能力，但 MCP 化尚未验证 | canonical descriptor 保留名称/schema；命令执行保留 sandbox/approval | P2-05、P5-13、P5-16 | 旧工具契约测试通过；MCP 不削弱命令安全边界 |
| MCP-05 | 新外部工具注册后自动可见 | 部分完成：动态目录存在但非真实 MCP | 受控 registry 完成 handshake 后发布 catalog | P5-02、P5-05、P5-11 | 未初始化 server 不可见；新增工具无需修改 graph/preset |
| AGT-01 | 保留 research/doc_qa/synthesis/ops 四个 preset | 部分完成且命名/语义不一致 | canonical role + legacy alias/variant | P2-12、P2-13、P4-08～P4-11 | 四角色具备稳定 contract；旧角色平滑映射 |
| AGT-02 | 每个 preset 有输入输出、工具权限和记忆策略 | 部分完成：contract 字符串化且未执行 | 版本化结构 contract | P2-13～P2-15 | schema 校验、memory scope 和 capability allowlist 被执行 |
| AGT-03 | 自定义 Agent 可注册并被编排发现 | 部分完成：registry 存在，主执行仍用旧 registry | canonical registry/discovery API | P2-17、P4-03 | 新增测试 preset 不修改主流程即可被发现和调度 |
| AGT-04 | 子 Agent 不直接访问底层实现 | 未完成：preset 接收完整 `UnifiedAgent` | 受限 `PresetContext` + `AuthorizedToolInvoker` | P2-14、P2-16 | preset 无 service-locator 穿透，架构测试通过 |
| GRF-01 | 每次请求由执行图管理生命周期 | 未完成：主路径仍用旧 dispatch/GraphRuntime | bootstrap 时编译静态主图，每次请求创建 run | P3-03～P3-08 | request/run/thread ID 明确，所有 profile 经图管理 |
| GRF-02 | 条件路由与轻重路径 | 未完成真实图 | IntentDecision 驱动条件边 | P3-05～P3-08 | chat 使用轻路径，workflow 使用完整子图 |
| GRF-03 | 长任务 checkpoint、回放和恢复 | 部分完成：仅进程内兼容 saver | 官方 PostgreSQL checkpointer | P3-09～P3-11、P4-06 | 服务重启后同 thread 恢复，不同 thread 隔离 |
| GRF-04 | 独立步骤并行执行 | 部分完成：自研线程并行 | LangGraph fan-out、确定性 reducer、有界并发 | P4-02、P4-03、P4-05 | 并行结果确定，race loser 不取消整个 run |
| GRF-05 | memory write、事件通知作为固定后置节点 | 未完成：仍散落在 Agent | finalize/post-processing 节点，副作用幂等 | P4-13、P4-16 | 崩溃恢复不重复写入，后置行为由图可视化和测试 |
| CFG-01 | 默认→共享→local→env→CLI 配置分层 | Phase 1 已完成 | 不可变配置与明确深度合并规则 | P1-01～P1-03、P1-11 | 优先级、mapping/list、`.env` 和未知字段测试通过 |
| CFG-02 | secret 不进入版本控制 | 部分完成：VenAgent 本地与 GitHub refs 已清理；AGI-saber 不属于 VenAgent 运行面 | local/env/secret reference + 自动脱敏 | P0-01～P0-04、P1-03 | tracked 文件无真实 secret |
| CFG-03 | 基础设施按能力降级 | Phase 1 已完成 | capability health 明确 durable/non-durable 可用性 | P1-08、P1-10 | 单个设施失败不阻塞无关功能，状态可诊断 |
| CFG-04 | 分阶段启动且失败可诊断 | Phase 1 已完成 | Bootstrapper + FastAPI lifespan | P1-04～P1-10 | 初始化/关闭顺序可测，资源无泄漏 |
| GOV-01 | 统一查看任务状态 | 部分完成：单全局 current task | tenant/owner 绑定的 run repository/use cases | P2-03、P2-08、P2-18、P4-07 | list/status 只返回授权 run，状态稳定可查询 |
| GOV-02 | 取消运行中的任务 | 部分完成：当前 `cancel_all()` | per-run cancel | P0-12、P0-15、P4-07 | 取消一个 run 不影响并发 run |
| GOV-03 | 业务 snapshot 与 checkpoint 分离 | 部分完成：概念存在，持久化语义不完整 | 官方 checkpoint 与业务 run projection 分表 | P2-03、P2-18、P3-10、P3-11 | 两类存储独立、迁移可回滚、关联可审计、恢复测试通过 |
| SEC-01 | 高危命令有权限和审计 | 部分完成：sandbox 有校验，但权限链不完整 | Sandbox 独立安全契约 + 一次性审批证据 | P2-07～P2-09、P5-13 | 无审批拒绝；无 secret/宿主路径/socket/未授权网络 |
| SEC-02 | MCP 注册和远程调用安全 | 未完成 | server registry、SSRF/DNS/redirect/egress 防护 | P5-02、P5-07～P5-09、P5-14 | 私网/metadata/重绑定被阻断，凭据不进模型或日志 |
| SEC-03 | run/checkpoint 不可跨主体访问 | 未完成，且 PRD 未显式定义认证模型 | tenant/principal/run 对象级授权 | P2-08、P4-07 | list/status/SSE/resume/cancel/approval 均验证 owner |
| MIG-01 | 渐进迁移和兼容层 | 已完成部分壳层 | profile-based Strangler | P3-12、P3-13、P6-01、P6-05 | 可按 profile 回切；legacy 保留约定发布周期 |
| MIG-02 | 每步有测试门禁和回滚 | 部分完成：已有测试但缺迁移门禁 | characterization/conformance/crash/E2E 分层 | P0-06～P0-10、P3-13、P4-14、P7-01～P7-04 | 每 Phase 验收通过后才能进入下一 Phase |
| MIG-03 | AGI-saber 不持续漂移 | 未在原 PRD 明示 | 冻结参考提交，白名单移植 | P0-05 | 参考版本和移植政策写入接受的 ADR |
| MIG-04 | 源码退出 `final` 单目录并保持渐进迁移 | 用户新增约束：当前目录职责混乱 | `apps/ + src/venagent/ + tests/config/deploy`，`final` 为有时限兼容壳 | P1-04、P6-09、P7-07 | 新包不反向导入 `final`；稳定窗口后无引用删除旧目录 |
| NFR-01 | HTTP API 与前端交互不变 | 已完成重要基线；真流式 token 时序是明确的目标变更 | Handler/RuntimeEvent 兼容边界；保持 envelope/字段/结束语义 | P0-07、P3-04、P3-14、P6-03、P7-04 | characterization、OpenAPI schema diff、真流式 contract 和关键 E2E 通过 |
| NFR-02 | 错误安全、内部诊断充分 | 未完成：存在 `detail=str(e)` 和静默失败 | stable error code + request/run correlation + 脱敏日志 | P0-14、P1-03、P4-04 | 客户端不见内部异常，服务端可按 ID 诊断 |
| NFR-03 | 文件职责单一且不超过 800 行 | 未完成：Agent/Handler 仍过重，代码集中在 `final` | application façade、route 拆分和目标 `src` 目录 | P1-04、P6-02～P6-04、P6-09、P7-07 | 生产文件不超过门禁，目录依赖和架构测试通过 |
| NFR-04 | 关键用户路径回归 | 部分完成：单测较多，浏览器 E2E 不完整 | chat/RAG/tool/document/resume E2E | P0-07、P0-08、P7-04 | 关键流程在兼容客户端上通过 |
| NFR-05 | 不改写底层算法、不新增基础设施 | 满足规划 | 复用现有底座和 PostgreSQL；只新增库依赖 | 全阶段约束 | RAG/memory/document 算法保持；无新增 DB/MQ 服务 |

## 三、审查发现的遗漏及处置

以下遗漏在本次最终审查中被识别，均已进入任务清单或明确列为决策，不再作为隐含工作：

| 遗漏 | 影响 | 处置 |
|---|---|---|
| 缺少自定义 Agent 注册/发现的显式任务 | 无法证明“新增角色不改主流程” | 新增 P2-17，并在 P4-03 验证调度 |
| 缺少固定 memory/event 后置节点任务 | PRD 4.4 的后置处理要求可能遗漏 | 新增 P4-16，纳入 crash/idempotency 测试 |
| 缺少基础工具契约兼容任务 | time/weather/exec 在 MCP 化时可能漂移 | 新增 P5-16，保护名称/schema/响应 |
| 关键 ADR 只有文档建议、没有任务生产者 | identity/config/checkpoint 等任务依赖无法闭环 | 新增 P0-16，明确 ADR-001/003/004/007/012/013；P0-05 负责 ADR-011 |
| 业务 run projection 只有 Port、没有仓储和 schema 迁移任务 | 无法证明 checkpoint 与业务状态真正分表 | 新增 P2-18，并接入 P2-08/P4-07 验收 |
| HTTP 兼容门禁未显式保护 OpenAPI | 路由拆分可能产生未察觉的 schema 漂移 | 扩展 P0-07/P6-03/P7-04，建立 OpenAPI 基线与差异验证 |
| 目标目录仍把全部新模块放在 `final/internal` | 与新的目录约束冲突，旧耦合会固化 | 新增目标目录设计及 P1-04/P6-09/P7-07，采用 `apps/ + src/venagent/` 渐进迁移 |
| 缺少独立的最终追踪和决策文档 | 需求、计划和未决项难以闭环 | 本文件作为规划审查入口 |
| `.claude` plan 与路线图安全门禁描述不同步 | 执行时可能错误声称历史零命中 | 同步计划的历史处置/豁免语义 |
| 旧 Phase1 文档被暂存删除但去向未定 | 文档提交范围无法闭合 | 用户已确认不再保留，允许删除，不创建 archive |
| 根 README 仍声称 MCP 边界和 Phase1 已完成 | 对完成度产生错误认知 | 更新为当前审计结论和新文档入口 |
| 目标设计章节编号跳过 7.3 | 文档质量问题 | 修正 Sandbox/Contract 小节编号 |

## 四、依赖与关键路径

### 4.1 外部依赖

| 依赖 | 用途 | 引入时点 | 当前状态 |
|---|---|---|---|
| 仓库所有者授权 | 若历史命中 secret，决定是否重写历史 | Phase 0 | 命中后阻塞清理；可记录有时限的风险豁免 |
| 用户批准新增依赖 | 锁定 LangGraph、PostgreSQL saver、MCP SDK | P0-10/P3-01/P5-01 | 待批准，不得提前修改 requirements |
| PostgreSQL | durable checkpoint 与业务 run projection | Phase 3 | 复用现有基础设施，不新增服务 |
| 真实 MCP 测试 server | 协议 conformance 与故障测试 | Phase 5 | 可使用固定测试 fixture/本地进程 |
| 认证主体来源 | tenant/principal 对象级授权 | Phase 2 | 当前产品认证模型待用户确认 |

### 4.2 内部关键路径

```text
Phase 0 安全与行为基线
  → Phase 1 配置与 Bootstrap
    → Phase 2 Ports、CapabilityBroker、AgentTeam 权限
      → Phase 3 真实 LangGraph 只读路径
        → Phase 4 工具、Workflow、恢复与副作用
      → Phase 5 真实 MCP client/server adapters
        → Phase 6 默认切换与 legacy 清理
          → Phase 7 全量验证与交付
```

Phase 5 可在 Phase 2 后并行开发，但默认切换必须等待 Phase 4 和 Phase 5 同时通过。任何 durable workflow 上线都依赖 run identity、对象级授权、官方 checkpointer 和副作用幂等。

## 五、非目标与边界

- 不重写 RAG、memory、document 的底层算法或存储逻辑；
- 不引入新的数据库、消息队列或向量基础设施；
- 不在本轮迁移中把同步栈整体改成 async；
- 不拆微服务；
- 不把 Managed Agents 或特定 LLM 厂商 SDK纳入本次重构；
- 不让 MCP 成为所有进程内调用的强制 wire protocol；
- 不持续同步 AGI-saber；
- 不在未授权时添加依赖、启动 Compose、重写 Git 历史、推送或创建 PR。

## 六、需用户决策事项

以下选择会改变实现或验收。用户已于 2026-07-18 接受 D-01～D-14 的全部推荐项；后续若要推翻某项决定，应新增 ADR 或显式修订本规划，不得在实现中静默偏离。

| ID | 决策 | 已确认选择 | 其他选择 | 状态 | 影响 |
|---|---|---|---|---|---|
| D-01 | MCP 的进程内定位 | **内部 Ports + MCP 边界适配器** | 所有内部调用强制走 MCP | 已确认（2026-07-18） | 后者会增加序列化、故障域和测试成本 |
| D-02 | LangGraph 运行模式 | **先同步 API，沿用 SSE worker bridge** | 本轮同步改造全栈 async | 已确认（2026-07-18） | 后者显著扩大改动面和风险 |
| D-03 | Checkpoint 存储 | **官方 PostgreSQL saver，独立于业务 snapshot** | 自研 saver / 仅内存 | 已确认（2026-07-18） | 决定重启恢复与升级维护成本 |
| D-04 | 四个 canonical preset 映射 | **research/doc_qa/synthesis/ops；writer/review/doc 作为 variant/operation** | 保留旧四名称为顶层角色 | 已确认（2026-07-18） | 决定 contract、兼容 alias 和文档 workflow |
| D-05 | AGI-saber 定位 | **冻结 `python@2b995c...` 为参考，不持续同步** | 继续作为代码上游 | 已确认（2026-07-18） | 决定后续差异管理成本 |
| D-06 | 旧 Phase1 文档 | **永久删除，不归档** | 恢复或归档 | 已确认（2026-07-18） | 当前目标架构、目录设计和路线图成为唯一规划依据 |
| D-07 | 身份与授权模型 | **先定义 `tenant_id/principal_id` Ports，单用户部署提供固定本地主体** | 本轮直接实现完整登录/多租户系统 / 暂不做对象级授权 | 已确认（2026-07-18） | PRD 未要求新登录 UI，但 durable run 必须防止跨主体访问 |
| D-08 | PostgreSQL 不可用时的 durable 行为 | **chat 可降级；需恢复的 workflow 明确拒绝或经确认以 non-durable 运行** | 全部静默降级为内存 | 已确认（2026-07-18） | 静默降级会造成错误的恢复承诺 |
| D-09 | `/api/docs/delete` 语义 | **真实删除索引与文档记录；失败则明确报错** | 软删除 / 移除该兼容接口 | 已确认（2026-07-18） | 决定数据一致性和 API 兼容测试 |
| D-10 | Legacy runtime 保留窗口 | **新路径全量默认后保留 1 个稳定发布周期** | 立即删除 / 保留多个版本 | 已确认（2026-07-18） | 决定旧 run 恢复和维护成本 |
| D-11 | 性能回归阈值 | **Phase 0 只记录 legacy 伪流式基线；Phase 3 实现真流式后，以 TTFT、增量间隔、完成时间和取消延迟建立目标门禁，不要求复刻伪流式时序** | 用户指定其他阈值 | 已确认（2026-07-18） | 决定 Phase 3/6 发布门禁 |
| D-12 | 依赖引入授权 | **允许在 P0-10 隔离环境验证，版本确认后再改 requirements** | 只做文档研究 / 立即加入生产 requirements | 已确认（2026-07-18） | 决定能否验证真实兼容性 |
| D-13 | AGI-saber 参考仓库的凭据范围 | **仅作静态参考，不纳入 VenAgent 运行面；不执行外部账号操作** | 将 AGI-saber 纳入当前安全处置范围 | 已确认（2026-07-18） | VenAgent 独立完成自身 tracked secret、历史扫描和清理 |
| D-14 | 目标源码目录 | **`apps/ + src/venagent/ + tests/ + config/ + deploy/`；`final` 仅作迁移壳并在稳定窗口后删除** | 继续在 `final/internal` 内扩展 | 已确认（2026-07-18） | 决定新模块位置、依赖方向和旧目录退役门禁 |

## 七、规划完成判定

本轮“探索与规划”在满足以下条件后视为完成：

- [x] PRD 与当前实现逐项对齐；
- [x] AGI-saber 与 VenAgent 的关系、可复用项和冻结策略明确；
- [x] 目标架构、拒绝方案和建议 ADR 明确；
- [x] 全阶段路线、任务、依赖、门禁和回滚明确；
- [x] 遗漏项已经补入任务清单；
- [x] 需用户决策事项集中列出；
- [x] 用户确认第六节全部决策；
- [x] Phase 0 执行计划获批准并已启动。

当前执行已完成 VenAgent 历史凭据清理、GitHub master 强制更新、测试基线和 Compose 安全模板；仍需完成依赖版本确认、characterization/performance/coverage 和其他安全门禁。AGI-saber 仅作为静态参考，不纳入本项目处置范围。
