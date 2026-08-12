# VenAgent 紧凑模块路线完整目标规格

## 1. 目标

VenAgent SHALL 在已完成的 M01--M03 之后，使用由简至繁、逐模块批准的紧凑路线。每个候选项代表一个完整产品域，而不是把同一领域的自然组成部分拆成若干编号相邻模块。

路线只定义后续选择与审计单位；每个模块仍必须经过独立的 intake、Shape、用户批准、Build、Verify 和 Archive，任何路线项都不自动授权实现。

## 2. 架构不变量

- M01 conversation-context、M02 streaming-run-lifecycle 和 M03 conversation-persistence 的已确认行为保持不变。
- `thread_id`、`run_id` 与未来 `owner_id` 分别表示对话隔离、运行身份和数据所有权，不得混用。
- 官方 LangGraph checkpointer 只保存图执行状态；长期可查询记忆、任务业务事实、文档与运行事件使用独立 VenAgent 领域模型。
- AGI-saber 只提供行为、接口、依赖、测试与风险事实；VenAgent SHALL NOT 迁移其 Go 实现、运行期 DDL、表结构或内部架构。
- 每个模块都必须交付自身最小 UI/API、安全、测试、降级和可观测性体验。

## 3. 候选模块目录

1. `M01 conversation-context`：线程身份、有限多轮上下文、线程隔离与进程内 checkpointer。已完成。
2. `M02 streaming-run-lifecycle`：SSE、token 流、目标取消、断开和错误契约。已完成。
3. `M03 conversation-persistence`：conversation/checkpoint 持久化、重启恢复、迁移和清理。已完成。
4. `M04 ownership-lifecycle`：可选身份、`owner_id`、授权边界、用户数据删除和保留生命周期。
5. `M05 memory-system`：长期事实提取、来源、语义召回、Hash/Embedding 去重、重要性与 TTL、冲突/quarantine/superseded、审计/删除、图记忆和记忆上下文预算。用户画像与用户偏好明确不在范围内。
6. `M06 tool-execution`：在模型→工具→模型循环进入实现前，先交付最小沙箱、最小权限、审批、取消交接和审计框架；随后在同一产品域内按明确授权逐步加入 MCP、Skill/manifest、外部工具注册、执行 adapter 和产物访问边界。最小框架不得默认执行任意命令、访问用户文件或加载任意 MCP server。
7. `M07 agent-orchestration`：在 M06 的受控工具契约上实现模型→工具→模型循环、任务计划和图执行、运行时 Planner/Tool/Task context、重试/并行/恢复、子 Agent、产物与交付边界。
8. `M08 rag`：文档模型、上传解析、版本删除、基础 RAG、引用、检索评测，以及按证据选择的改写、重排、混合或图检索。VenAgent 自有 RAG SHALL 是内部领域服务与原生 Tool；未来可由 M07 通过受控 MCP façade 对外暴露，但 MCP 不替代内部检索调用。
9. `M09 platform-governance`：跨模块评测、性能与运行观测、部署、备份恢复、API 治理和供应链策略。

## 4. 依赖与边界

- M04 是 M05 及所有按用户存储或访问数据能力的前置条件。
- M05 可先提供长期事实与对话 recall；M07 把其扩展为 Planner、Tool 和 Task 共同参与的 Runtime Context Assembly。
- M06 在真实外部能力进入 Agent 前建立最小受控执行框架；MCP、可安装 Skill、命令执行和高风险外部动作只可在 M06 的策略、审批和审计边界内扩展。M07 的首个工具循环只能调用 M06 已获准的工具。
- M08 的文档知识与 M05 的个人/对话记忆是不同数据域；它们可以共享上下文预算和召回接口，不能共用归属、删除或治理规则。
- M06 的高风险执行必须服从 M04 的授权边界，且不因 M07 已存在任务图而自动获准。
- M09 不替代此前模块自身的安全、测试、可观测性或用户体验验收。

## 5. AGI-saber 参考边界

M05 可参考 AGI-saber 的事实抽取、双阶段去重、图关系、中心度保护、TTL/Importance、quarantine、superseded 和槽位化上下文装配目标；但不得复用其图节点缺少 `user_id`、全局时序边及图扩展后未重新按 owner 过滤的做法。

M07 可参考其任务图、Planner、replan、Task Memory、Tool State 和子 Agent 的用户可见语义；VenAgent 必须通过 LangGraph 的公开 State、checkpointer、interrupt 与并发契约实现。

M08 可参考其文档解析、向量/BM25/图检索和 RRF 的产品目标；实际检索架构应由 M08 的评测和 `search-first` 决定。

M06 可参考其 MCP、Skill、Docker/local/mock sandbox 与审计的能力边界；不得把 GitHub 仓库描述伪装为已执行插件，也不得复制不受授权控制的外部执行路径。

## 6. 前端与目录演进

前端与目录结构 SHALL 随各产品模块同步推进，而不是作为最后的统一补债或另一个空泛的重构模块。路线定义的是能力拥有权和依赖约束，不是未来文件树的预分配。

每个模块 Shape SHALL 明确：用户或操作者的最小操作、正常/加载/失败/降级/无权状态、该体验是扩展既有页面还是需要新表面、以及在当前代码中最小且内聚的后端和前端位置。M04--M09 的能力名称（包括 `tool-execution` 与 `rag`）不得被解释为预先要求同名目录。

当前 `conversation/`、`agent/`、`infra/`、`interfaces/http/` 与 `web/src/modules/chat/` 是已经实现的事实边界。后续实现可以在证据支持时扩展它们，或新增 feature package/module；选择必须说明依赖方向、现有内聚性、真实复用和迁移成本。

无论具体路径如何，业务用例 SHALL 不依赖具体 adapter；`infra/` SHALL 不承载 feature use case，`interfaces/http/` SHALL 不承载业务事实。共享目录、组件、store、抽象层或路由只能在至少两个已实现能力存在稳定真实复用时创建，不得为未来路线预建。

M06 Shape SHALL 特别确定 sandbox 的策略/审批/审计边界和具体执行 adapter 的位置。它可以采用现有模块扩展或新 package，但必须保持策略与具体 Docker/local/mock/remote 执行实现可替换，且不让 adapter 绕过授权。

### 6.1 当前已实现目录

当前仓库的有效实现边界如下；这是事实展示，不是未来模块的模板：

```text
venagent/
  agent/                 # LangGraph state、graph、run 与当前 Agent runtime
  conversation/          # 线程生命周期、对话用例、legacy import
  infra/
    config/              # 配置 adapter
    llm/                 # provider adapter
    platform/            # PostgreSQL / memory persistence adapter
  interfaces/http/       # FastAPI、SSE、HTTP schema 与错误映射
web/src/
  app/                   # router
  modules/chat/          # 已完成的聊天工作区
```

### 6.2 模块目录决策点

| 模块 | 默认从何处检查 | Shape 时决定什么 | 不应预设什么 |
|---|---|---|---|
| M04 | `conversation/`、HTTP、现有 config | owner/授权是扩展现有对话能力还是形成独立 feature | 身份 UI 或 package 名称 |
| M05 | `agent/`、conversation state、platform adapter | 记忆是否形成独立领域，及其与 graph state 的单向接口 | `memory/` 的必然存在或图/向量 adapter 路径 |
| M06 | agent tool boundary、`infra/`、HTTP | 工具策略、审批、sandbox adapter 的最小位置与替换边界 | `tool/`、`sandbox/` 或 MCP client 的固定树形 |
| M07 | `agent/`、`modules/chat/`、M06 工具契约 | 哪些任务状态扩展既有 agent/chat，哪些需要独立任务表面 | `tasks/` 目录、子 Agent 目录或全局 state |
| M08 | conversation/agent、HTTP、前端聊天表面 | RAG 是扩展现有表面还是新增文档工作流，及领域与 adapter 分离 | `rag/`、`documents/`、vector/graph provider 的固定树形 |
| M09 | 已实现模块与运维需求 | 是否需要独立 operator surface，或只增加后端观测 | `governance/`、`operations/` 或管理 UI |

### 6.3 ECC 目录规划触发

每个模块固定使用其路由规定的基础 intake。若该模块 Shape 发现需要新增、合并或迁移 Python package、Vue module、共享表面、路由或跨模块所有权，SHALL 额外调用 ECC `product-capability`。

该能力输出的目录决策 SHALL 记录：能力与用户表面、固定约束、当前相关目录、候选增量、选择理由、保持兼容的迁移边界，以及明确不创建的未来空壳。目录决策只在该模块范围内有效；它不替代 Comet Native 的 Shape/Build/Verify/Archive，也不授权预建未来模块。

## 7. 路由与验证

模块路由矩阵 SHALL 对 M04--M09 分别记录固定 intake、专项能力、AGI-saber 对照主题和前端最小检查点。

每个模块的 AGI-saber 对照 SHALL 先从路由矩阵指定的优先路径开始，而非重扫旧项目全仓库。优先路径不是封闭白名单：当直接调用、被调用接口、共享数据模型、配置或相关测试证明当前信息不足时，审计可以扩大到最小必要范围。Shape 产物 SHALL 如实记录初始范围、实际扩展路径、扩展原因，以及这些额外事实对采用、舍弃或风险结论的影响。

本路线变更 SHALL 使 canonical 路线、路由矩阵及所有受影响相邻规格的模块名称和依赖引用一致。它不改变运行时代码，也不选择具体第三方基础设施或依赖。
