# Outcome

在核心重构路线中显式规定 M06/M07 与 M08 引入后对既有 M05 记忆能力承担的共存、隔离和回归验证责任，避免只描述模块所有权而遗漏跨 provider 验收。

# Scope

- 修订 canonical `refactor-roadmap` 的 `tool-aware-agent-graph`（M06 + M07）条款，增加 M05 共存验收。
- 修订 `rag-evidence`（M08）条款，增加 M05 隔离验收和 evidence 提升为记忆时的规格变更边界。
- 修订全局发布与验证规则，要求新增 ContextProjection provider 的 change 重跑相关既有 provider 回归，并覆盖跨 provider 的来源隔离、预算竞争、授权和降级矩阵。

# Non-goals

- 不实现或修改 M05、M06、M07、M08 运行时代码、数据库、API、前端或测试。
- 不提前创建 `tool-aware-agent-graph`、`rag-evidence` capability spec、provider、目录或空 adapter。
- 不在本 change 决定具体工具结果来源字段、evidence 提升协议、预算数值或未来模块实现方案。

# Acceptance examples

- 路线明确要求 M06/M07 Verify 证明未授权工具结果、计划、观察和失败尝试不污染 M05；明确授权的工具结果只能通过 M05 application port 和既有安全策略形成候选。
- 路线明确要求 M08 Verify 证明 evidence 与个人记忆不混合、不共享事实权威或删除生命周期，M08 上线不改变 M05 G1 基线，并覆盖双 provider 的预算、隔离、故障和删除行为。
- 路线明确规定：若后续 change 改变 M05 来源资格或允许 evidence 提升为长期记忆，必须同步修订 M05 canonical spec 并重新验证相应来源、生命周期和召回行为。
- 全局 Verify 规则明确由新增 ContextProjection provider 的 change 承担相关既有 provider 回归与跨 provider 组合验证，不要求为此另开独立 M05 change。

# Constraints and invariants

- M05、M06、M07、M08 继续各自拥有权威事实；ContextProjection 只组合已经由各模块过滤完成的 ContextBlock。
- 新模块的普通共存验证不等于从头重做 M05；只有修改 M05 语义时才修订 M05 规格并扩大评测。
- 完整目标规格必须保留现有路线顺序、模块边界、非目标和验证要求，不以增量补丁替代完整规格。

# Decisions

- [confirmed] M06/M07 与 M08 各自在自身 Build/Verify 中承担 M05 共存或隔离回归，不另建专门的 M05 回归 change。
- [confirmed] 3.3、3.4 和全局 Verify 三处都显式写入责任，避免仅依赖通用测试条款推断。
- [confirmed] evidence 或工具结果若改变 M05 来源语义，必须同步修订 M05 canonical spec；仅作为并列 provider 时执行针对性共存回归即可。

# Open questions

- 无。

# Verification expectations

- 对比拟议完整规格与当前 canonical 规格，确认只增加已批准的三组规划条款且其余内容完整保留。
- 使用定向文本检索确认 M06/M07、M08 和全局 Verify 均存在 M05/跨 provider 验收要求。
- 运行 `git diff --check` 和 Comet scoped text safety check；本 change 只有规划 Markdown，不运行 Python、Vue 或数据库测试，并如实记录跳过原因。
