# Outcome

生成一份中文研究参考文档，解释 AGI-saber 的设计思路与工程取舍，为 VenAgent 核心重构提供代码之外的行为/理念参考；文档不是 VenAgent 的运行规格，也不授权迁移旧项目实现。

# Scope

- 输出路径：`docs/discussions/agi-saber-design-reference.md`。
- 资料来源分层：语雀 AGI-Core 当前公开目录与核心设计文章；本机 AGI-saber 代码/架构文档的静态证据；VenAgent 当前 canonical specs 与已接受的旧项目参考边界。
- 解释 AGI-saber 的主设计链路：复杂度路由（chat/tool/RAG/ReAct）、Static DAG 到 Plan-and-ReAct、五类记忆与 promptctx 槽位、混合 RAG 与 evidence、工具/MCP/沙箱、子 Agent/文档库、持久化/快照/降级/观测。
- 每个主题说明：设计目标、机制、收益、代价/风险、可验证事实来源，以及对 VenAgent 的 Adopt / Extend / Compose / Do-not-copy 结论。
- 文章章节与模块路由显式对齐：每章标注一个或多个 M04--M09 关联模块、可进入 Shape 的问题、以及不应提前创建的目录/能力。
- 增加一张“AGI-saber 主题 → VenAgent 模块 → 设计输入”映射表，避免研究结论停留在泛化架构描述。
- 明确参考版本、访问时间和“行为参考而非迁移模板”的边界；不把语雀文章中的愿景、面试材料或不确定实现细节写成 VenAgent 契约。

# Non-goals

- 不修改 VenAgent 业务代码、API、数据库、Vue 模块或目录所有权。
- 不迁移 AGI-saber 的 Go/Python 实现、表结构、运行期 DDL、依赖或部署配置。
- 不建立第二套 Agent State、事件溯源、通用兼容层或未来模块空壳。
- 不把当前语雀内容持续同步为自动化输入；后续变化须重新研究并人工记录来源。

# Acceptance examples

- 文档开头能用一页说明 AGI-saber 的总体设计原则，并区分“观察到的事实”和“面向 VenAgent 的建议”。
- 读者能从每个主题追溯到至少一个语雀文章 URL 或仓库相对路径/提交证据。
- 文档明确指出：路由优先级、动态重规划、记忆分层、混合检索、工具安全边界和可降级运行之间如何形成一条完整执行链。
- 文档对 VenAgent 至少给出一条“不直接照搬”的边界，特别是业务 ID、LangGraph State、权限/工具事实、MCP 与 sandbox 的所有权。
- 文档为后续 M04--M09 Shape 提供可复用的设计问题，而不是预先决定未选择模块的实现字段或目录。
- 每个 M04--M09 关联章节都包含最小 Shape 输入：事实证据、建议边界、待验证假设、验收关注点和明确非目标。

# Constraints and invariants

- VenAgent 的 canonical specs、项目 AGENTS.md 和 Comet Native 生命周期优先于 AGI-saber 的行为线索。
- AGI-saber 只能作为静态行为/接口/依赖/测试/风险事实来源；不作为 VenAgent 的运行、部署或持续同步路径。
- 研究稿使用中文；技术名词、代码符号、路径和 URL 保持原样。
- 当前工作树已有用户改动，Build 只新增该研究文档与 Native 产物，不回退或重写无关文件。

模块路由 intake（跨模块研究参考，不创建 M04--M09 功能）：

模块：跨模块 AGI-saber 设计参考（非功能模块）
基础 intake：`ecc-rules-pack-common`、`ecc-rules-pack-python`、`search-first` 均可读取；本任务无 Python 实现
专项能力：无；已读取模块矩阵，用于确定对照主题边界
search-first：仓库搜索 + 固定 AGI-saber 提交 + 已打开的语雀页面；采用 Compose（组合多源事实与 VenAgent 约束），不新增依赖
AGI-saber：ownership、memory、tool/sandbox、agent orchestration、RAG、platform/degradation/observability
AGI-saber 范围：优先读取语雀“架构总览”、Plan-and-ReAct、记忆系统、RAG、Saber 工具调用全流程；本机读取冻结提交与当前架构文档作为最小必要扩展
目录：仅新增 `docs/discussions/agi-saber-design-reference.md`；不触发 `product-capability`，不新增 package、Vue module、路由或共享表面
前端：无产品 UI 变更；不适用正常/加载/失败/降级/无权 UI 验收

# Decisions

- 文档定位为“研究参考/决策输入”，不写入 `docs/comet/specs/`，避免与 VenAgent canonical 行为规格混淆。
- 采用“事实 → 设计意图 → VenAgent 取舍”的固定章节结构；每章同时写收益与代价。
- 资料 provenance 分为：语雀概念说明、本机代码/架构证据、VenAgent 当前契约；语雀内容不自动覆盖代码事实。
- 对 VenAgent 的默认结论是：保留问题意识与边界，采用类型化端口/明确所有权/可验证降级；不复制旧项目的全局 agent、隐式 prompt 拼装、关键词路由作为最终权威、私有持久化或无审批副作用执行。
- 文章与模块路由采用以下固定关系：
  - M04 ownership-lifecycle：owner 隔离、文档/记忆访问边界、删除、健康与降级可见性；重点把 AGI-saber 的全量 memory/document 暴露列为反例。
  - M05 memory-system：STM、Preference、LTM、GraphMemory、TaskMem、抽取/去重/衰减/冲突/召回与 promptctx 槽位；不把 TaskMem 或 Prompt 当作长期记忆权威。
  - M06 tool-execution：Tool/MCP 注册、snapshot、沙箱、审批、取消、审计和副作用幂等；把 AGI-saber 的 JSON fallback 与缺少完整审批链列为取舍输入。
  - M07 agent-orchestration：路由、Planner、TaskGraph、并行、Replanner、子 Agent、恢复和任务进度；不得将旧图状态直接变成 VenAgent 顶层 State。
  - M08 rag：文档生命周期、父子块、query rewrite、Dense/BM25/图检索、RRF、rerank、evidence 与删除一致性；PG/索引分层只作为行为事实，不迁移其表结构。
  - M09 platform-governance：可选依赖、启动并发、降级、health/readiness、事件总线、观测和备份恢复；不因文章存在就提前创建 scheduler/operator/queue。
- 跨模块主线：路由 → Context/Memory → Tool/RAG → Plan/ReAct → Finalizer/Observation；该主线只解释依赖关系，不替代 M04--M09 各自的所有权。

# Open questions

- 已确认：按上述范围生成 `docs/discussions/agi-saber-design-reference.md`，作为 VenAgent 重构的非规范研究参考；文章章节与 M04--M09 模块路由显式关联。

# Verification expectations

- 检查文档内所有来源路径、固定提交和语雀 URL 可追溯且不包含凭据。
- 运行 Comet 文本卫生检查，并进行一次人工一致性复核：未把 AGI-saber 实现写成 VenAgent 事实，未引入未来模块空壳，章节结论与当前 canonical specs 不冲突。
