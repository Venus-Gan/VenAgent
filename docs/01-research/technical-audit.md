# VenAgent 重构现状审计与重新规划依据

> 审计日期：2026-07-17  
> 需求来源：[VenAgent 重构 PRD](../02-requirements/PRD/venagent-refactor.md)  
> VenAgent 实现事实源：`final/` 当前源码与测试  
> AGI-saber 参考源：`D:/VSCProject/AGI-saber` 当前 `python` 分支工作树  
> 目的：替换过时的 AGI-saber 初始审计，为完成 VenAgent 全量重构建立新的事实基线。

## 一、结论摘要

旧审计的方向仍然成立，但状态判断已经明显过时。VenAgent 已经完成一轮“边界壳层”重构：

- 已新增结构化 `IntentPolicy`、执行档案和能力范围；
- 已新增 `RuntimeGovernance` 门面；
- 已建立 AgentTeam contract、registry 和四个兼容 preset；
- 已建立工具目录规范化层；
- 已把 SSE 从完成后逐字符回放升级为工作线程驱动的真实 token/进度流；
- 已增加名义上的 `langgraph` 包、thread ID、进程内 checkpoint 和 resume 测试。

但当前还不能称为完成 PRD：

1. `IntentPolicy` 仍依赖旧关键词路由，且其 `graph_entry`、agent/memory/recovery scope、澄清决策没有被完整执行。
2. `final/internal/agent/langgraph/` 是项目自研的兼容实现，不是真实 LangGraph；生产 ReAct 仍由自研 `GraphRuntime` 调度。
3. 当前 MCP 只是工具元数据和普通 HTTP/闭包包装，没有协议初始化、工具发现、标准调用和会话生命周期。
4. AgentTeam 权限仍是描述性元数据，preset 可直接穿透访问 `UnifiedAgent`、RAG、工具执行器和文档写入。
5. 配置只是在多个候选 YAML 中选择一个文件，不符合 PRD 要求的逐层深度合并；启动副作用仍集中在 `UnifiedAgent.__init__()`。
6. checkpoint 与业务 snapshot 尚未真正分离；现有 checkpoint 只存在于进程内，服务重启即丢失。
7. `UnifiedAgent` 和 Handler 仍过重，运行治理还是进程级/全局状态，不适合并发 run。
8. 安全基线仍存在阻断项：默认基础设施凭据、CORS、错误详情、任意 MCP endpoint 注册和全局取消。

因此，新的完成路线不应重复“新增壳层”，而应执行第二阶段迁移：

> 安全与基线 → 配置/bootstrap → 内部 Ports 与授权 → 真实 LangGraph → 工作流/AgentTeam → 真实 MCP → 默认切换和 legacy 清理。

## 二、事实源与 AGI-saber 基线

### 2.1 VenAgent

- 当前运行应用位于 `final/`。
- 当前依赖清单没有 `langgraph`、LangGraph PostgreSQL checkpointer 或 MCP Python SDK，见 [requirements.txt](../../final/requirements.txt)。
- 当前 PRD、目标架构和目标目录设计是规划事实来源；旧 Phase1 SDD 已确认退出当前文档体系，不再保留为实施依据。

### 2.2 AGI-saber

AGI-saber 仓库当前结构存在两条不同技术线：

- `python` 分支是本次可直接比较的 Python/FastAPI 行为参考；当前 checkout 指向 `2b995cdd8b2fb413bfb34c41456ec0bda92e6c2a`，并包含未提交工作树变化。
- `main` 分支是 Go 技术线，不应被误当作 Python 代码的线性后继。

重新对比后的结论：

- VenAgent 已吸收 AGI-saber Python 主体，并在策略、治理、SSE、checkpoint 兼容层和 AgentTeam 上继续演进。
- 没有发现需要整目录回同步的 AGI-saber 新功能。
- AGI-saber 应冻结为行为参考，而不是 VenAgent 的持续代码上游。
- 后续只允许“先写 VenAgent 回归测试，再白名单移植单个修复”，禁止目录覆盖、无审查 cherry-pick 或自动同步。

### 2.3 紧急安全发现

AGI-saber 当前已跟踪的 `final/config/config.yaml` 工作树中存在两项疑似真实第三方 API 凭据。本文不记录其值。

必须立即执行：

1. 在对应服务商侧撤销并轮换；
2. 检查调用、计费和异常访问记录；
3. 新凭据仅存放于被忽略的本机配置或仓库外 secret；
4. 扫描全部分支、标签和 Git 历史；
5. 若历史命中，在轮换后再经仓库所有者授权执行历史清理。

这项处置独立于 VenAgent 重构，不得因“可能尚未提交”而延后。

## 三、PRD 目标对齐矩阵

| PRD 能力 | 当前状态 | 证据 | 结论 |
|---|---|---|---|
| 结构化 IntentPolicy | 部分完成 | [intent_policy.py:72-102](../../final/internal/agent/policy/intent_policy.py#L72-L102)、[types.py:75-114](../../final/internal/agent/policy/types.py#L75-L114) | 决策结构已建立，但分类仍复用旧 router |
| 澄清优先 | 部分完成 | [intent_policy.py:199-209](../../final/internal/agent/policy/intent_policy.py#L199-L209)、[agent.py:597-606](../../final/internal/agent/agent.py#L597-L606) | 能判定 `CLARIFY`，但最终仍落入 chat，没有专用澄清节点 |
| 工具能力标准化 | 部分完成 | [mcp_catalog.py:37-58](../../final/internal/tools/mcp_catalog.py#L37-L58) | 只统一了目录字段，schema 表达能力仍弱 |
| 真正 MCP server/client | 未完成 | [tools.py:328-359](../../final/internal/tools/tools.py#L328-L359)、[handler.py:589-602](../../final/internal/handler/handler.py#L589-L602) | 普通 HTTP/闭包包装，不是 MCP 协议 |
| 可扩展 AgentTeam | 部分完成 | [contracts.py:17-54](../../final/internal/agentteam/contracts.py#L17-L54)、[registry.py:21-59](../../final/internal/agentteam/registry.py#L21-L59) | contract/registry 已有，权限和隔离未执行 |
| 四个 PRD preset | 部分完成且语义不一致 | [presets/](../../final/internal/agentteam/presets/) | 当前是 research/writer/review/doc；PRD 是 research/doc_qa/synthesis/ops |
| 真实 LangGraph 编排 | 未完成 | [builder.py:88-177](../../final/internal/agent/langgraph/builder.py#L88-L177)、[runtime.py:66-96](../../final/internal/agent/langgraph/runtime.py#L66-L96) | 本地同名实现；`ReactRuntime` 仍继承 `GraphRuntime` |
| checkpoint/resume | 部分完成 | [runtime.py:23-63](../../final/internal/agent/langgraph/runtime.py#L23-L63)、[test_langgraph_resume.py:25-113](../../final/tests/test_langgraph_resume.py#L25-L113) | 仅进程内，不能证明重启恢复 |
| 业务 snapshot 与 checkpoint 分离 | 部分完成 | [snapshot.py:17-35](../../final/internal/repo/snapshot.py#L17-L35) | 概念上有两套对象，但业务表只是 latest-state upsert，官方 checkpoint 尚不存在 |
| 统一运行治理 | 部分完成 | [runtime_governance.py:22-93](../../final/internal/agent/runtime_governance.py#L22-L93) | 已有 façade，但依赖 agent 内全局 registry/current task |
| 配置分层 | 未完成 | [config.py:219-241](../../final/config/config.py#L219-L241) | 当前是候选文件择一，不是默认→共享→本地→env→CLI 合并 |
| 分阶段 bootstrap | 未完成 | [main.py:42-47](../../final/main.py#L42-L47)、[agent.py:113-202](../../final/internal/agent/agent.py#L113-L202) | 构造器仍执行恢复、沙箱、KG、线程等副作用 |
| 基础设施优雅降级 | 已完成基础能力 | [infra.py:273-326](../../final/internal/infra/infra.py#L273-L326) | 应保留，不得由编排层吸收 |
| HTTP/SSE 契约兼容 | 已完成重要基线 | [handler.py:209-366](../../final/internal/handler/handler.py#L209-L366) | 需要以 characterization tests 保护 |
| 配置安全 | 未完成 | [config.yaml:20-32](../../final/config/config.yaml#L20-L32)、[config.yaml:84-91](../../final/config/config.yaml#L84-L91) | 仍有默认基础设施密码，local secret ignore 也需统一验证 |

## 四、当前重构增量

### 4.1 IntentPolicy

主流程已通过 [agent.py:545-548](../../final/internal/agent/agent.py#L545-L548) 使用 `IntentPolicy.resolve()`，并产生：

- execution profile；
- prompt schema key；
- graph entry；
- tool/agent/memory/recovery capability scope；
- clarify flag；
- confidence 和 reason。

但是 [intent_policy.py:5-8](../../final/internal/agent/policy/intent_policy.py#L5-L8) 仍导入 `detect_tool`、`need_react`、`need_tool`；策略层当前是旧规则的结构化包装，不是最终决策引擎。

此外，当前运行只消费 profile 和 tool scope；其他决策字段仍主要停留在数据结构中。

### 4.2 RuntimeGovernance

[runtime_governance.py](../../final/internal/agent/runtime_governance.py) 已收口：

- token 注册与取消；
- current task；
- 内存 snapshot；
- 业务 snapshot 持久化；
- agent/infra status。

但取消 API 仍调用 `cancel_all()`，见 [handler.py:368-375](../../final/internal/handler/handler.py#L368-L375)；多个并发用户无法按 `run_id` 隔离。

### 4.3 SSE

VenAgent 相对 AGI-saber 的显著进展是：

- 使用工作线程执行同步 agent；
- 使用有界 `asyncio.Queue` 桥接到 SSE；
- 支持 route、token、RAG/ReAct progress、step、tool call、done；
- 客户端断开时取消 token；
- 所有事件附带相同 `request_id`。

这应作为不能回归的兼容基线。

### 4.4 AgentTeam

当前已具备：

- 冻结的 `PresetTask`/`PresetContract`；
- 保序、线程安全 registry；
- 拆分的 research/writer/review/doc preset；
- legacy `subagents.py` 兼容层。

但 contract 中 `memory_policy` 和 `retrieval_policy` 仍是字符串；preset runner 接收整个 agent，并直接访问具体实现，例如 [research.py:47-64](../../final/internal/agentteam/presets/research.py#L47-L64) 和 [doc.py:50-69](../../final/internal/agentteam/presets/doc.py#L50-L69)。这不满足权限隔离。

### 4.5 “LangGraph”兼容层

当前本地 `StateGraph`：

- 自己维护 node、edge、queue 和 state merge；
- `compile()` 没有绑定官方 checkpointer；
- 不具备官方 superstep、interrupt、Command resume 和持久化语义；
- 生产 `ReactRuntime` 只是对自研 `GraphRuntime` 加了一层内存 checkpoint。

相关测试很有价值，但它们只能作为迁移行为基线，不能证明真实 LangGraph 已落地。

## 五、AGI-saber 对比结论

| 范围 | AGI-saber Python | VenAgent | 规划判断 |
|---|---|---|---|
| 路由 | 关键词函数直接调用 | IntentPolicy 包装旧规则 | 继续完成 VenAgent 策略迁移 |
| SSE | 完成后逐字符回放 | token/进度真实桥接 | 以 VenAgent 为事实源 |
| ReAct | 自研 GraphRuntime | 自研 runtime + checkpoint 壳 | 迁移真实 LangGraph，不能回退 |
| AgentTeam | 单文件固定注册 | contract/registry/presets | 完成权限和 canonical role |
| 工具目录 | 旧 `parameters` | `params` + 兼容 alias | 保留 VenAgent 规范化层 |
| Tavily | 配置存在即进入默认路径 | 只保留显式工具，不默认外联 | 不回同步；未来通过受控 adapter 接入 |
| RAG | 有重复不可达分支 | 已清理并增加流式路径 | 以 VenAgent 为事实源 |

冻结建议：

- 行为参考提交：AGI-saber `python@2b995cdd8b2fb413bfb34c41456ec0bda92e6c2a`；
- 未提交工作树仅作为人工差异输入，不作为可复现上游；
- 从此不再把 AGI-saber 新提交自动列为 VenAgent 待同步项。

## 六、共同 legacy 与新增风险

### P0 / P1

1. **安全凭据与默认密码**：见 2.3 和配置矩阵。
2. **假 MCP 注册**：`/api/tools/mcp` 名称与行为不符；未来直接接通还会引入 SSRF。
3. **全局取消**：一个请求可取消所有 in-flight 请求。
4. **秒级 task ID**：[agent.py:900](../../final/internal/agent/agent.py#L900) 存在并发碰撞。
5. **同步调用阻塞 async route**：[handler.py:193-207](../../final/internal/handler/handler.py#L193-L207)。
6. **错误详情回传**：多处 `detail=str(e)` 可能泄露内部诊断。
7. **CORS 默认通配符 + credentials**：[handler.py:173-181](../../final/internal/handler/handler.py#L173-L181)。
8. **删除文档接口可能虚假成功**：[handler.py:377-388](../../final/internal/handler/handler.py#L377-L388) 仅在 RAG 有 `delete` 时执行。

### P2

1. `UnifiedAgent` 仍是 service locator 和组合根。
2. Handler 直接穿透 agent 和 repo。
3. `RuntimeGovernance` current task 不支持多 run。
4. checkpoint 不能跨进程恢复。
5. 副作用节点没有统一幂等键，恢复可能重复写 document/memory/event。
6. [agent.py:1008-1038](../../final/internal/agent/agent.py#L1008-L1038) 重复定义 `_save_agent_snapshot()`，后者覆盖前者。
7. 事件发布和聊天记录写入仍有静默失败路径。

## 七、当前官方实践核对

### 7.1 LangGraph

Context7 文档源：`/websites/langchain_oss_python_langgraph`。

关键约束：

- 使用官方 `StateGraph`、显式 state schema、reducer 和 `compile(checkpointer=...)`；
- 用 `configurable.thread_id` 隔离 checkpoint；
- 单元测试可使用官方内存 saver，生产恢复使用官方 PostgreSQL saver；
- 人工暂停/恢复使用 `interrupt()` 和 `Command(resume=...)`；
- 并行字段必须有确定性 reducer；
- 外部副作用仍需应用级幂等，checkpoint 不提供 exactly-once。

建议保持当前同步业务栈，先采用同步 LangGraph API；现有 SSE worker thread 可以承载阻塞图执行。不要把本轮重构扩大为全栈 async I/O 改造。

### 7.2 MCP Python SDK

Context7 文档源：`/modelcontextprotocol/python-sdk/v1.12.4`。

真正 MCP client 的最低流程是：

1. 建立 stdio 或 Streamable HTTP transport；
2. 创建 `ClientSession`；
3. `initialize()`；
4. `list_tools()`；
5. `call_tool()`；
6. 处理 session、标准结果、错误和关闭。

真正 MCP server 应使用 SDK server/FastMCP 能力，提供标准 tools/resources/prompts，并由宿主应用 lifespan 管理 session manager。

推荐架构不是“所有进程内调用都走 MCP wire”，而是：

> 内部强类型 Ports + 本地适配器 + true MCP client/server adapters。

这既满足上层只依赖标准契约和后端可替换，也避免把模块化单体过早变成分布式系统。

### 7.3 Claude/Agent API 规划注意事项

当前 VenAgent 是 provider-neutral 的原生 HTTP LLM 客户端，不应在本轮架构重构中顺手改成特定厂商 SDK。

如果未来接入 Claude：

- 应使用官方 Anthropic SDK，而不是 OpenAI-compatible shim；
- tool schema 和结构化输出应使用官方 SDK 类型；
- 长上下文、tool loop、streaming、stop reason 和错误类型需要独立适配；
- Managed Agents 是托管控制平面，不应与本地 LangGraph/MCP 重构混为一项需求。

## 八、规划影响

本审计支持以下实施原则：

1. 保留 RAG、memory、document、repo、infra、sandbox 和 HTTP/SSE 行为。
2. 不再新增第二套“兼容壳”；下一步必须让现有边界真正生效。
3. 配置、安全、run identity 和 bootstrap 必须先于真实工作流迁移。
4. LangGraph checkpoint 与业务 snapshot 必须分开。
5. MCP 作为边界适配器，不作为所有内部调用的强制 wire protocol。
6. AgentTeam 权限必须在 planner 和 executor 两次执行，默认拒绝。
7. 按 execution profile 渐进切换，先只读路径，最后迁移副作用工作流。
8. 每个阶段都保留显式回滚开关，legacy 至少保留一个稳定发布周期。
9. 新边界进入 `src/venagent/`，`final/` 只保留当前实现和迁移期兼容入口，禁止继续承接新架构模块。

详细目标架构见 [VenAgent 重构目标架构](../03-design/venagent-refactor-target-architecture.md)，目录迁移见 [VenAgent 目标目录层次与迁移边界](../03-design/venagent-target-directory-structure.md)，实施路线见 [重构路线图](../04-planning/roadmap.md) 和 [任务清单](../04-planning/venagent-refactor-task-list.md)。

## 九、本次验证限制

本轮已完成源码、测试、Git 分支、官方文档和开源模式的静态核对。探索与规划阶段没有执行以下运行验证，不能声称当前基线已经通过；它们是 Phase 0 的首个执行门禁，不依赖特定代理或终端分类服务：

```bash
cd final && python -m pytest tests
python -m compileall -q final
cd final && python -m pytest tests --cov=internal --cov-report=term-missing
```

覆盖率仅在 `pytest-cov` 已安装时执行；未经批准不新增测试依赖。以上验证是 Phase 0 的首个门禁。
