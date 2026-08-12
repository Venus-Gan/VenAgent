# Outcome

使 M01 `conversation-context` canonical 规格准确反映该模块已经批准、实现并完成验证的状态，不再保留“拟议”或“后续实现”等过时措辞。

# Scope

- 将规格标题从“Conversation Context 完整目标规格（拟议）”改为“Conversation Context 完整目标规格”。
- 将验收基线引导语从面向未来实现的措辞改为当前持续验收契约。
- 保留全部 M01 行为要求、模块边界和验收条目不变。

# Non-goals

- 不修改 VenAgent 运行时代码、Web UI 或测试。
- 不改变 M01 的线程、状态、并发、错误或存储契约。
- 不新增或实现 M02、M03、M03A、M04 能力。

# Acceptance examples

- 规格标题不再包含“拟议”。
- 第 8 节明确表示这些项目是当前实现必须持续满足的验收基线，而不是尚待实现的要求。
- 除上述状态措辞外，canonical 规格内容与现有 M01 契约一致。

# Constraints and invariants

- `conversation-context` capability ID 和文件位置保持不变。
- 使用完整目标规格 replace，不编写增量补丁规格。
- 本 change 为纯文档状态修正，不把浏览器回归结果扩展成新的产品能力。

# Decisions

- 用户已批准执行此前明确提出的 M01 最终文档收尾。
- 验收引导语采用“当前实现 SHALL 持续使用不访问网络的可控假模型证明”。

# Open questions

无。

# Verification expectations

- 对拟议规格与 canonical 规格做有界差异检查，确认只有两处预期措辞变化。
- 检查规格仍包含全部七项既有验收条目和 M02/M03/M03A/M04 边界。
- 运行 Comet 内置文本检查并完成无代码变更验证。
