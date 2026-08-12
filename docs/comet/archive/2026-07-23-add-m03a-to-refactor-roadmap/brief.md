# Outcome

明确舍弃 M03A `conversation-library` 路线候选，并清除 M01 规格中对该候选模块的待办引用，使 M01 在既有已实现契约范围内正式收尾。

# Scope

- 保持 canonical `refactor-roadmap` 的 M01–M18 模块目录不新增 M03A。
- 从 M01 `conversation-context` 相邻模块边界中删除 M03A 建议。
- 明确归档、文件夹、分叉、原生备份导入/导出和会话资料引用不进入当前 VenAgent 路线。
- 明确未来只有新的显式路线修订 change 才能重新评估这些能力，不能因旧审计建议自动恢复。

# Non-goals

- 不删除或改变 M01 已实现的多轮上下文、线程隔离、localStorage 可见记录或线程清理能力。
- 不改变 M02、M03、M04 或其他候选模块的现有边界。
- 不实现或设计任何会话库、归档、文件夹、分叉、导入、导出或资料引用功能。
- 不修改运行时代码、Web UI 或测试。

# Acceptance examples

- 路线目录仍按 `M01 → M02 → M03 → M04` 排列，不出现 M03A。
- M01 canonical 规格不再把 M03A 或归档、文件夹、分叉、导出记录为后续待办。
- 路线明确记录 M03A 及会话库候选能力为 `drop`，不会被后续模块静默恢复。
- M01 现有八节行为契约和七项验收基线保持不变。

# Constraints and invariants

- `drop` 的含义遵循既有路线规则：当前不进入 VenAgent，未来不得因旧项目或旧审计存在而自动恢复。
- M01 的完成状态不依赖 M03A，也不把 M01 localStorage 提升为持久会话事实源。
- 本 change 只修订 canonical 文档状态，不产生运行时实现范围。

# Decisions

- 用户明确决定：M03A 引出的上下文预算、恢复语义、导入、分叉和资料引用问题过多，不追求面面俱到，整体抛弃 M03A。
- M01 按当前已实现、已测试并完成浏览器回归的契约宣告收尾。
- 原 `add-m03a-to-refactor-roadmap` change 改为记录最终 drop 结论，不创建第二个 change。

# Open questions

无。用户已确认 M03A 及相关会话库能力整体 drop，M01 按现有契约正式收尾。

# Verification expectations

- 差异检查确认 refactor-roadmap 只新增 drop 治理结论，模块目录仍无 M03A。
- 差异检查确认 conversation-context 只删除 M03A 相邻模块说明，其余行为和七项验收基线不变。
- 文本断言确认 M03A 不在候选目录、drop 边界明确且无实现变化。
