# Outcome

完成 M05 记忆模块的职责边界修复：LLM 包只负责 provider/config/factory；记忆模型适配、结构化提取提示词、冲突判断和摘要构造归回 `memory/`；embedding 与 graph memory 各自拥有明确子包。代码行为保持兼容，同时让目录、命名和依赖方向能够表达真实所有权。

# Scope

- 将 `venagent/llm/memory.py` 的 M05 模型适配实现迁移到 `venagent/memory/` 下的职责明确文件，并由 `bootstrap.py` 继续装配。
- 保留 `venagent/llm/embeddings.py` 作为 M05/M08 可复用的通用 HTTP embedding adapter；创建 `venagent/memory/embedding/`，只收拢 M05 embedding port、index records 与 index application logic。
- 创建 `venagent/memory/graph_memory/`，收拢 GraphMemory application service 与 disabled graph implementation；repo/platform 仍保留 Neo4j adapter 与运行时资源所有权。
- 更新 bootstrap、service、jobs、recall、ports、repo、platform、测试和公开内部导出，删除含义过宽的 `llm/memory.py` 与 memory 根目录中已迁移的旧文件路径；`llm/embeddings.py` 保持稳定。
- 强化结构化 extractor system prompt：明确来源资格、稳定事实边界、敏感信息与提示注入排除、assertion/temporal 枚举、source span 偏移和空候选行为，并保留严格 JSON schema。

# Non-goals

- 不改变 HTTP/API、命令语法、数据库 schema、迁移版本、owner/tenant 隔离、删除/撤销/lifecycle、Graph G1 1-hop 语义或 embedding 降级策略。
- 不把 PostgreSQL/Neo4j adapter、连接池、配置模型或 platform runtime 移入 memory 子包。
- 不新增独立 embedding/graph 产品能力，不引入新的向量数据库、图 schema 或兼容旧的永久 shim。
- 不从 assistant 文本建立长期事实，不放宽敏感信息、偏好、问题、否定、假设和引用的既有拒绝策略。

# Acceptance examples

- `venagent.llm` 只导出配置/provider/factory 及通用模型能力，包括 `venagent.llm.embeddings.HttpEmbeddingClient`；导入 `venagent.llm.memory` 失败。
- `venagent.memory.embedding` 能提供 `MemoryIndex` 与 `EmbeddingPort`；`venagent.memory.graph_memory` 能提供 `GraphMemory` 与 disabled store；bootstrap 分别从通用 LLM embedding adapter 和 M05 子包完成装配。
- 提取提示词包含稳定事实、来源、敏感信息/注入排除、六种 assertion mode、四种 temporal scope、半开 source span 和无候选输出规则；fake model 的既有 schema 测试继续通过。
- 普通事实提取、索引 job、Graph G1 投影、embedding 失败降级和现有 HTTP/浏览器流程结果不变。

# Constraints and invariants

- 依赖方向保持 `interfaces -> feature services/ports <- repo/platform/model adapters`；具体 adapter 只在 `bootstrap.py` 装配。
- `memory/` 持有 M05 业务协议与用例；`repo/` 只实现 port；`platform/` 只管理资源、迁移和启动状态；`llm/` 不承载 M05 事实、schema 或 prompt。
- 业务用例不依赖具体 provider；模型 adapter 只消费通用 `MessageInvoker`，不创建 provider、连接池或外部资源。
- 所有公共 Python 函数保持类型标注和显式边界验证；不在错误或测试输出中泄露原文、凭据或 embedding 向量。

# Decisions

- 采用 `venagent/memory/embedding/` 与 `venagent/memory/graph_memory/` 两个 M05 子包；memory embedding 只包含 M05 port/index，通用 client 保留在 `llm/embeddings.py`，graph_memory 下保留 application service 与 disabled implementation。
- M05 的模型调用适配文件使用职责明确的命名并位于 `memory/`，不继续使用 `memory.py` 或 `llm/memory.py` catch-all 命名。
- 继续由 `llm/factory.py` 构造通用 chat model；M05 adapter 由 `bootstrap.py` 注入该模型。
- 提示词采用结构化多行契约文本，模型负责候选识别，确定性 extractor/policy 继续负责 schema、来源、敏感性、生命周期和最终写入门控。
- 提示词以本机 AGI-saber `fead7687a82965b3c0106728089ccde0cc0eb3e8` 的 `internal/application/chat/mem_writer.go` 为事实对照，吸收其稳定/非临时、第一方来源、第三方排除、敏感信息排除和提示注入防护；不复制 assistant/exchange 派生、偏好持久化、KV schema 或旧项目写入架构。
- 用户已确认本契约，并要求补完 `complete-m05-semantic-memory` 未完成的真实 PostgreSQL、Neo4j 与非模拟浏览器验收。
- 用户进一步确认 `llm/embeddings.py` 必须保留为未来 RAG 可复用的通用 HTTP embedding adapter，不归入 M05 memory 所有权。

# Open questions

- 无。

# Verification expectations

- 运行 Comet scoped check、受影响 pytest（memory semantics/index/graph/persistence/config/bootstrap/API）及完整项目 pytest。
- 运行 Ruff、compileall、前端构建；确认新旧模块引用无残留，旧路径不作为运行时兼容 shim。
- 运行真实 PostgreSQL/Neo4j 集成测试与真实环境浏览器验收；分别记录事实写入、embedding/index、Graph G1 和 ContextBlock 注入证据。
- 若真实 provider 不可用，记录实际 skipped reason，不把 fake model 或总 READY 状态写成真实 provider 通过。
