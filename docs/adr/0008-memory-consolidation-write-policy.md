# ADR-0008: 长期记忆沉淀式写入策略

长期记忆不逐条实时写入：每 N 条（默认 5，可配置）用户消息或会话静默（默认 10 分钟）先到先触发一次**沉淀（consolidation）**——窗口内多轮消息聚合为一次 LLM 抽取（事实只从用户陈述取，助手回复仅作上下文辅助指代消解），经既有 decide_merge/quarantine/supersede 链落库；pending 状态只存 PG 游标（conversation 级「已沉淀到 sequence=X」，不复制消息内容），复用现有 job 队列 retry/fencing，不引入外部组件。显式「记住/忘记」指令保持同步即时写（显式即时、隐式沉淀双轨）。不做「会话边界」触发事件，也不加「最迟时限 T」守卫——计数窗口本身即 pending 存留的最迟条数上界，两条件已互相兜底。

动因：逐条「每轮一次 LLM 抽取」成本高且过早固化（第 k 轮事实第 k+1 轮被纠正时，要靠后续抽取打补丁，中间态事实可被召回）；窗口聚合让窗口内改口一次抽对（同槽位以最后一次陈述为准），抽取成本降为约 1/N，decide_merge 收敛为只管跨窗口冲突。业界佐证：mem0 V3 单遍 ADD-only + 后台 Dream、Letta dreaming 按 N 步触发、LangGraph 官方后台写入建议、LangMem 静默期 debounce、ChatGPT/Claude 的显式即时双轨（调研：`docs/wayfinder/assets/长期记忆写入策略-研究.md`）。

代价（接受）：窗口内新事实暂不在长期 recall——本会话由短期记忆（近期 turn 原文）承接，跨会话召回最多延迟 N 条或空闲阈值。

来源：Wayfinder 票 `长期记忆写入策略`（resolved）。
