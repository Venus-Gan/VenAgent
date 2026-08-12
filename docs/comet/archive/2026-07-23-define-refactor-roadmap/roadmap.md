# VenAgent 选择性重构路线

## 1. 总体方向

VenAgent 采用“稳定内核 + Ports + 可替换 Adapters + 逐阶段能力”的架构：

```text
Web UI / API
    ↓
Application services（请求、线程、权限、事件契约）
    ↓
LangGraph runtime（state、node、edge、stream、checkpoint）
    ↓
Domain capabilities（conversation、memory、tools、rag、documents）
    ↓
Ports → local / PostgreSQL / vector / MCP / sandbox adapters
```

核心原则：

- 用户可见行为先于基础设施。
- 每种状态只有一个清晰身份和生命周期。
- 先单进程可验证，再替换持久化后端。
- 先串行正确，再考虑并行、竞速和多 Agent。
- 旧项目功能默认不迁移；只有阶段 Shape 明确批准后才进入范围。
- 所有阶段保留离线测试替身，不依赖真实密钥或外部服务完成验收。

## 2. 阶段总览

| 阶段 | 主题 | 核心交付 | 状态 |
| --- | --- | --- | --- |
| Phase 0 | 最小运行内核 | 单节点 Agent Loop、真实模型适配器、基础 Web UI | 已完成 |
| Phase 1 | 会话运行时 | `thread_id`、多轮历史、内存 checkpointer、SSE、会话隔离 | 下一候选 |
| Phase 2 | 持久化与身份 | checkpoint/chat repository、数据库迁移、可选 owner/auth、恢复/取消 | 待审批 |
| Phase 3 | 分层记忆 | 偏好、长期语义记忆、召回、安全审计、删除/替代 | 待审批 |
| Phase 4 | 工具与沙箱 | ToolNode/循环、结构化结果、审批、MCP 安全、sandbox | 待审批 |
| Phase 5 | 文档与 RAG | 文档版本、切分、检索、引用、评测、可选混合检索 | 待审批 |
| Phase 6 | 任务规划与多 Agent | 任务状态、并行/恢复、子 Agent、产物交付 | 待审批 |
| Phase 7 | 产品化与平台治理 | Vue 功能解锁、Skill、观测、部署、性能与安全加固 | 待审批 |

## 3. Phase 0：最小运行内核（已完成）

已交付：

- LangGraph START → agent → END 单节点图。
- LangChain OpenAI 兼容模型适配器和离线回显模型。
- FastAPI `/api/chat`、健康检查和基础 Web UI。
- 无凭据测试和配置隔离。

当前限制：每次请求只有当前消息；无 thread、stream、checkpoint、tools、RAG、长期记忆。

## 4. Phase 1：会话运行时

### 目标

让“新对话”“切换会话”“连续追问”在前后端具有一致语义，建立后续所有状态能力的根。

### 候选范围

- 请求与响应加入稳定 `thread_id`。
- LangGraph 使用进程内 checkpointer 保存线程消息。
- 同一 thread 保留多轮；不同 thread 严格隔离。
- Web UI 会话列表与后端 thread 对齐；新对话生成新 thread。
- 增加 SSE token/完成/错误事件，保留同步 API 作为兼容路径。
- 明确窗口或 token budget；不无限增长上下文。
- 提供 thread 清空/删除的最小行为。

### 明确非目标

- 不接 PostgreSQL、不做用户账号、不做长期语义记忆。
- 不做工具、RAG、摘要压缩或多 Agent。

### 出口门槛

- 连续追问能使用同 thread 历史。
- 新 thread 不可读取旧 thread。
- 并发 thread 无串话；取消仅影响目标 run。
- 内存存储替换时不改变 API 和图状态契约。

## 5. Phase 2：持久化与身份

### 目标

把 Phase 1 的稳定线程契约接到可恢复存储，同时区分聊天记录和 LangGraph checkpoint。

### 候选范围

- 定义 `ConversationRepository`、`CheckpointStore` 和 migration 边界。
- 选择 PostgreSQL 或阶段审批的其他后端，支持重启恢复。
- 引入 `run_id`、幂等写、恢复、线程删除和数据保留策略。
- 评估个人单用户模式与账号/JWT模式；核心状态预留可选 `owner_id`。
- 健康/就绪接口准确反映持久化能力，不静默伪装成功。

### 明确非目标

- 不在聊天表中保存长期语义记忆。
- 不引入 Milvus、Elasticsearch、Neo4j 或 Kafka。

### 出口门槛

- 重启后目标 thread 可恢复。
- checkpoint 与业务消息可独立清理和审计。
- 数据迁移、失败回滚和并发写有测试。

## 6. Phase 3：分层记忆

### 目标

在对话历史之外增加可解释、可控、可删除的用户偏好和长期语义记忆。

### 候选范围

- 分开 `Profile/PreferenceMemory` 与 `SemanticMemory`。
- 每条记忆记录 owner、来源消息、类别、时间、重要性和状态。
- 写入策略先采用显式/规则候选，再评估 LLM 抽取；不默认记住全部回答。
- 召回进入独立 context slot，设 top-k/token budget 和来源标注。
- quarantine、superseded、冲突处理、查看和删除接口。
- 初始可使用 PostgreSQL + 简单检索；向量库须由评测证明需要。

### 明确延期

- Neo4j 图记忆、中心度保护和自动复杂合并。
- 从 AI 回答自动生成长期事实，除非安全评测通过。

### 出口门槛

- thread 历史、用户偏好和语义记忆不会互相替代。
- 不同 owner 隔离；匿名模式不会跨会话召回。
- 敏感信息、注入文本、删除与替代路径有测试和审计证据。

## 7. Phase 4：工具与沙箱

### 目标

把单节点回答扩展为可终止、可审计的模型 → 工具 → 模型循环。

### 候选范围

- LangChain tool schema 与 LangGraph ToolNode/条件边。
- 步数、超时、重试和输出预算。
- 结构化 tool result 与 UI 事件。
- MCP endpoint allowlist、DNS/IP/redirect 校验、响应大小和凭据策略。
- Docker/mock sandbox；local backend 默认关闭。
- 高风险动作人工审批和最小权限。

### 出口门槛

- 无工具问题不进入工具循环。
- 工具失败可解释且不会无限重试。
- SSRF、路径越界、命令注入、超大输出和取消有安全测试。

## 8. Phase 5：文档与 RAG

### 目标

提供可度量、带引用的个人知识库，而不是一次性复制三路检索基础设施。

### 候选范围

- 文档/版本/来源/删除契约与解析边界。
- 递归切分和父子块作为候选策略。
- 先实现一种可本地测试的检索后端及离线评测集。
- query rewrite、rerank、hybrid RRF 分别以指标证明增益后加入。
- 回答必须携带可追溯引用。

### 明确延期

- Neo4j 知识图谱与 Milvus+ES+Neo4j 三路同时上线。
- 文档自动生成、RAG 自动回灌等闭环。

### 出口门槛

- ingestion、删除、重建索引和引用一致性通过测试。
- 有固定数据集的召回/排序质量和时延基线。

## 9. Phase 6：任务规划与多 Agent

### 目标

仅在工具和 checkpoint 稳定后，处理复杂多步骤任务与交付物。

### 候选范围

- 显式 task state、计划节点、依赖、状态机和恢复。
- 先串行计划执行，再按真实瓶颈引入并行。
- 子 Agent 使用隔离上下文、预算和结果契约。
- research/writer/review/doc 作为候选工作流，不预设全部保留。
- 产物写入独立 workspace Port。

### 出口门槛

- 中断、恢复、重试、幂等和部分失败有端到端测试。
- 并行不会共享当前任务、工具观察或取消状态。
- 每个子 Agent 的输入、输出、权限和成本可审计。

## 10. Phase 7：产品化与平台治理

### 目标

在核心能力稳定后完成产品体验、部署和运营边界。

### 候选范围

- Vue UI 按已完成后端能力逐项启用知识库、工具、记忆管理和任务视图。
- 评估 Skill 系统：仅 prompt、MCP manifest 或受控代码插件。
- 结构化日志、trace、指标、LangSmith 评测与成本观测。
- API 版本、限流、备份恢复、数据保留、部署与性能测试。
- 对外发布前补充许可证与供应链策略。

### 出口门槛

- 前后端 E2E、权限、安全、性能和恢复演练通过。
- 降级状态对用户可见，不以 mock 伪装真实能力。

## 11. 审批与执行规则

- 本路线批准后，首先只启动 Phase 1 的独立 Comet change。
- 每阶段 Shape 必须重新审计相关旧代码和当前 VenAgent，不直接沿用本路线的候选项。
- 每阶段由用户确认目标、用户可见行为、非目标和验收标准后才进入 Build。
- 阶段完成并归档后，再决定是否进入下一阶段或调整路线。
- 某项能力若缺少收益证据，可延期或永久舍弃，不因旧项目存在而自动实现。
