# ADR-0009: 计划层上下文装配——节点 prompt 内联 + 每 run 一次 mem_prefix 统一复用

计划层（selector/planner/executor/replanner/generator/rag_answer）不建专属 prompt 文件（`promptctx/source_planner.py`/`source_rag.py` 不建），**节点专属 prompt 保持节点内联**；另由 `AgentRuntime._build_planning_mem_prefix`（`venagent/agent/runtime.py`）**每 run 一次**完成投影装配（复用基线降级链 + `ProjectionInputCollector` + `ContextProjectionService().project(FOUNDATION_POLICY, input_budget=32_000)`），将 `projected.system_messages` 拼接为 mem_prefix，以 SystemMessage 前缀形式注入 planner/replanner/generator/rag_answer 四节点的节点内联 prompt（selector 不接——轻量结构化分类，带 rag_loaded 开关即可）。HumanMessage 任务文本全部不动；投影失败（含超时/异常）降级为 `mem_prefix=""`，行为等价 M07 现状（已验收）。

动因（AGI-saber 实证，`D:\VSCProject\AGI-saber`）：AGI-saber 每请求一次 `buildContextPrefix` 统一装配 memPrefix（6 槽 SlotProfile/SlotPlanner/SlotTaskMem/SlotToolState/SlotConstraints/SlotRecall，按 Mode 选 schema，单槽 budget 自治 + 全局按 slotPriority 裁剪），planner/终答/rag 的**节点级 prompt 仍内联**（plan_graph.go 的 planPrompt、mode_react.go 的 genPrompt、core_agent.go 的 rag 全 system 均为 memPrefix + 内联规则文本）；`source_planner.go`（SlotPlanner/PlannerProvider）的真实语义是**任务状态跨轮快照**（PlannerSnapshot{TaskID/Status/Phase/NextStep...}），注入其他轮次与模式的上下文，不是 planner 节点自己的 prompt 来源；promptctx 无 RAG 槽位（检索证据由 rag 服务组装进 userMsg）。故定稿 §8 第 4/8/10 条（要求 source_planner 作 planner 上下文 / source_rag 进 promptctx）与实证不符，按实证改写（见 `docs/wayfinder/assets/m07-intake.md` §8 修订注记）。

代价（接受）：planner 层为元认知节点，历史/记忆仅经 mem_prefix 进入（无对话历史——conversation 段不注入，planner 缺信息有 clarify HITL 兜底）；generator/rag_answer 不带对话历史与 AGI-saber 行为一致（AGI-saber generator 有观察时同样丢弃 histMsgs）；mem_prefix 最长约 13k tokens（FOUNDATION_POLICY 预算上限 32k 的非消息段），快模型成本可控（缓解：缩 `input_budget` 至 16000，暂未启用）。

Phase 2（可选，未实现）：`source_planner` 按 AGI-saber SlotPlanner 跨轮语义落地（任务状态快照供给其他轮次）——VenAgent 目前 thread_id=run_id、无 currentTask 全局等价物，且任务视窗已覆盖该信息面，暂不做。

来源：Wayfinder M07 实现阶段 grilling 拍板 + 用户 2026-08-30 拍板 C'（对齐 AGI-saber 实证）；实施文档 `docs/wayfinder/assets/m07-计划层上下文装配计划.md`。
