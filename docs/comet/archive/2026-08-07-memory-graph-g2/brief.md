# Outcome

保持 AGI-saber 的模块边界：M05 个人图记忆继续只提供 G1 1-hop 召回，不在 M05 产品化 G2 多跳。当前 change 收缩为 G1 的安全、一致快照和评测强化，并清理此前为 M05 2-hop G2 准入实验新增的全部越界代码与规格。2-3 hop 文档知识图谱检索归 M08；本 change 只修正规划归属，不提前创建 M08 代码或目录。

# Scope

- 为既有 `MemoryStore` 增加 G1 recall snapshot application port，一次返回同一 owner/tenant 下用于本次召回的 memory settings、活动 facts、有效 sources 和当前注册表 edges。
- temporary adapter 在共享锁内捕获完整 G1 recall snapshot；PostgreSQL adapter 在一个只读、`REPEATABLE READ` 事务快照中读取对应数据，不实现 recursive CTE 或多跳遍历。
- `MemoryRecallProviderMixin.context_blocks` 只在单个一致快照上执行既有 G1 1-hop 排序；快照与请求的 owner、tenant、authorization epoch 或 deletion generation 不一致，或投影前复核发现 epoch/generation 已变化时，整批长期记忆候选 fail closed。
- 保留既有 G1 降级边界：完整 recall snapshot 不可读时省略 M05-L/G1；图边不可用但权威 facts/sources 能形成一致快照时，只省略 G1 邻居并保留普通长期事实召回，同时报告既有稳定 health reason code。
- 强化现有 `evals/memory` G1 评测与 pytest，覆盖直接召回对照、1-hop 增益、稳定排序、owner/tenant 隔离、授权/删除代次变化、生命周期/来源过滤、图降级和 temporary/PostgreSQL snapshot 等价性。
- 删除 `evals/memory/g2_*.py`、`evals/memory/schemas/g2_*.schema.json`、`tests/test_memory_g2_*.py`，并清除项目代码、拟议规格和验证文档中把 M05 2-hop 当作交付目标的引用。
- 用完整目标规格替换既有 `g1-recall-ranking` 和 `memory-context` capability；不创建 `memory-graph-g2` canonical capability。

# Non-goals

- 不实现或保留 M05 2-hop、多跳路径评分、path witness、graph-only=2、200-edge/100-target 预算、Gate A/Gate B、admission report/hash、G2 capability/config、recursive CTE 或 G2 私有索引。
- 不引入 Neo4j、NetworkX、Mem0、OpenViking、新图数据库 adapter 或新的 LangGraph Store。
- 不实现 M08 RAG/知识图谱，只在 M05 长期规格中把 2-3 hop 的所有权明确移交 M08。
- 不改变 G1 的 `FOLLOWS`/`SIMILAR_TO` 生成语义、`m05-g1-v1` 注册表、`m05-g1-recall-v2` 排序策略、严格注入阈值、总结果 limit 或最多一个 graph-only 候选。
- 不新增 HTTP API、`/memory` 命令、Vue surface、数据库权威列、新 Python package 或未来模块空壳。

# Acceptance examples

- 给定同一 owner/tenant 的活动事实、有效来源和 `SIMILAR_TO` 边，G1 仍只扩展 seed 的直接 1-hop 邻居，重复执行的候选和排序一致；二跳可达节点不会进入候选。
- 当 facts、sources 与 edges 在捕获期间并发变化时，temporary 使用同一把锁、PostgreSQL 使用同一事务快照，召回不会组合不同时点的数据。
- 当请求快照的 deletion generation 或 authorization epoch 在召回/投影前失效时，本次长期事实和 G1 图候选全部为空，不泄漏事实正文。
- 当图边读取失败而一致的普通事实快照仍可用时，召回退化为普通长期事实；当权威 facts/sources 快照不可读时，长期记忆整体为空，普通回答继续。
- G1 评测分别报告质量与安全指标；owner/tenant、deleted、expired、superseded、quarantine、revoked source、unknown registry 反例不得被召回。
- 清理后仓库不存在可执行的 M05 G2 evaluator、schema、runtime candidate、配置或测试；Comet 历史 evidence/runtime 作为不可改写的工作流记录保留，不算产品代码残留。

# Constraints and invariants

- 业务用例只依赖 `MemoryStore` port；adapter 负责各自的一致读取机制，`infra/` 不持有召回评分策略。
- `MemoryRequestSnapshot` 继续作为一次请求的 owner/tenant/epoch/generation/capability 控制快照；新增 G1 recall snapshot 是权威 memory 数据的一致读取结果，两者必须在召回前后校验一致。
- PostgreSQL snapshot 不通过多条独立 autocommit SELECT 拼接；temporary snapshot 不在多次锁获取之间拼接。
- 快照只返回当前 owner/tenant 作用域数据；unknown registry、非活动 edge、非活动/无有效来源/索引未 ready/已过期事实仍由 application 以既有规则过滤。
- 清理仅删除本 change 新增且已证明属于 2-hop G2 的项目资产；Comet state、trajectory、checkpoint、scope、verification receipt 等派生历史不手工编辑或删除。
- 现有 dirty worktree 中与本 change 无关的用户修改保持不动。

# Decisions

- 已确认（Q1-Q31，已被 Q32 收缩覆盖）：此前多跳方向、评分、数据准入、Gate A/Gate B、G2 capability、索引与降级选择只适用于已取消的 M05 2-hop 方案，不再约束产品实现；相关历史保留在 Native trajectory，不保留为当前目标规格。
- 已确认（Q32）：M05 保持与 AGI-saber 一致的个人图记忆模块边界，只交付 G1 1-hop；2-3 hop 移交 M08 RAG/知识图谱；当前 change 收缩为 G1 安全、原子快照和评测强化。
- 已确认（Q32 清理范围）：超过上述边界的 G2 代码全部清理，不保留“以后可能复用”的 evaluator、schema、测试、runtime candidate、配置、索引或空壳。
- 已确认（完整收缩契约）：用户批准本 brief 与 `g1-recall-ranking`、`memory-context` 两份完整目标规格，允许在 Build 清理 G2 项目资产并实现 G1 一致快照强化。
- 研究事实：AGI-saber `GraphMemory.RecallByFilter` 固定使用 1-hop；默认 2-hop、最多 3-hop 位于知识图谱/RAG `KGStore.Search`。VenAgent 不复制其 Neo4j 架构，只对齐模块行为边界。
- 实现决定：原子快照强化复用既有 `MemoryStore` ownership，不新增独立 graph package；G1 排序公式与关系注册表不变。

# Open questions

- 无。

# Verification expectations

- Build：先删除全部 G2 项目资产，再实现 G1 recall snapshot port、temporary/PostgreSQL adapter 和 application 复核，补齐聚焦 pytest。
- Verify：运行 G1 memory/adapter 测试、相关全套 pytest、Ruff/compileall（可用时）和 Comet 文本检查；PostgreSQL 集成环境不可用时如实记录，不把未运行写成通过。
- Archive：canonical 只替换 `g1-recall-ranking` 与 `memory-context`；不得创建 `memory-graph-g2` canonical spec。
