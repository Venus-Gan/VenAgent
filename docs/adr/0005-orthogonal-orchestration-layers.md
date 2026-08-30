# ADR-0005: 编排正交分层

执行层（M06 权威）与计划层（Planner → Selector → Executor → Replanner）正交分层，经稳定 Plan / NodeOutcome identity 对接；Replanner 事件驱动（节点失败 / 观察不足 / 依赖失效 / 前提改变）并产出完整 Plan revision。层内并行（MaxParallel 2）/ 竞速（RaceGroup）为后续增强，与 M07 整合时实现（多工具第一版纯顺序执行）。不使用 `create_deep_agent`；主 Agent 不兼任计划修改 / 工具授权 / 审批恢复 / 终止判断。

来源：Wayfinder 票 `剩余功能规划` Q4/Q6（resolved）。
