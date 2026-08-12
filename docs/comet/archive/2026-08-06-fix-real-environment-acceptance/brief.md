# Outcome

修复真实环境验收暴露的两个问题：M05-G1 图邻居在当前排序中无法对最终召回产生实际增益；同步 PostgreSQL checkpointer 在启动校验和 migration 中未复用运行期显式 msgpack allowlist，读取现有 checkpoint 时产生未来严格模式警告。修复后保持既有安全门槛、关系语义、数据库 schema 和公开 HTTP 契约不变。

# Scope

- 为 M05-G1 增加版本化、可解释的 1-hop `SIMILAR_TO` 路径相关性评分，并在既有 `limit` 内最多保留一个通过严格注入门槛的图扩展邻居。
- `FOLLOWS` 继续表达同一来源时间线的先后关系，不单独提供语义相关性加分。
- 普通长期事实和 G1 邻居继续执行 owner/tenant、授权、活动状态、来源、有效期、索引状态和预算检查。
- 抽取唯一 checkpoint serializer helper，显式允许 VenAgent `RunState` 中实际持久化的 dataclass；异步运行期、同步启动 schema 校验和显式 migration 全部复用该 serializer。
- 增加单元、真实 PostgreSQL、migration warning 和真实 HTTP/LLM 验收证据。

# Non-goals

- 不实现 G2 多跳、实体知识图谱、新关系类型、embedding 服务或新的 reranker 依赖。
- 不修改 `m05-g1-v1` 边注册表语义、边表 schema、已有边 ID 或迁移历史。
- 不允许 `FOLLOWS` 仅凭相连关系进入上下文，不降低秘密、特殊类别、删除、来源或授权安全门槛。
- 不修改 LangGraph 官方 checkpoint 物理表，不引入自定义序列化格式，也不清理现有 checkpoint。
- 不把沙箱网络限制导致的 `APIConnectionError` 作为应用缺陷；真实非沙箱模型请求已成功。

# Acceptance examples

- 当查询与一个种子事实相关，且该种子存在 `SIMILAR_TO` 邻居时，邻居的有效相关性取自身查询分数与“种子查询分数 × 注册表相似度下界”的较大值；只有有效分数达到原严格注入阈值才可竞争上下文名额。
- 同一次召回最多选择一个仅因图路径获得资格的邻居；直接相关事实继续按自身分数排序，返回总数不超过调用方 `limit`。
- 只有 `FOLLOWS`、自身查询分数低于注入阈值的邻居不得进入上下文。
- 关闭记忆、跨 owner/tenant、已删除/过期/隔离、来源失效或索引未 ready 的事实，即使图相连也不得召回。
- 真实 PostgreSQL 中写入事实、派生 G1 边、重启 runtime 后仍可复现相同选择；删除事实后活动边和召回结果立即移除。
- `python -m venagent migrate`、durable 启动 schema 校验和异步图恢复读取现有 `TaskInput`/`FinalAnswer` checkpoint 时不再输出 unregistered msgpack type 警告。
- 未列入 allowlist 的项目自定义 msgpack 类型在严格 serializer 下被拒绝，而不是退回全类型许可。

# Constraints and invariants

- 继续采用 feature-first；G1 评分留在 `venagent/memory/`，serializer 的状态类型声明属于 `venagent/agent/`，PostgreSQL adapter 只消费公开 helper。
- 候选召回与上下文注入保持两阶段；图路径分数是相关性重排输入，不绕过严格注入阈值。
- 使用 `SIMILARITY_THRESHOLD=0.45` 作为已注册 `SIMILAR_TO` 边的保守相似度下界，不伪造边中未存储的实际权重。
- G1 结果确定性不依赖数据库返回顺序；相同事实、边、查询和策略版本必须得到相同排序。
- checkpoint allowlist 必须显式、最小且集中；不得设置全局 `allowed_msgpack_modules=True`，不得记录 checkpoint blob 或秘密。
- 真实验收使用一次性账号并在结束后删除，不能把验收数据遗留在开发数据库。

# Decisions

- 保留现有直接召回阈值与严格注入阈值，不通过下调阈值制造 G1 增益。
- `SIMILAR_TO` 可以提供一跳相关性证据；`FOLLOWS` 不提供语义加分。
- 图扩展邻居在单次结果中最多占一个名额，总 `limit` 不变。
- checkpoint serializer 由 agent 公开 helper 唯一定义，platform runtime 和 migration 复用。
- 用户已确认以上修复契约，并要求在真实 PostgreSQL、真实模型请求之外，启动前端按真实用户操作路径完成一并验收。

# Open questions

- 无。

# Verification expectations

- 定向测试证明旧实现失败的新场景：图邻居能产生一个有界增益、`FOLLOWS` 不越权、低于有效门槛不注入、limit/排序稳定。
- 现有 M05 memory、agent runtime、migration 与真实 PostgreSQL 测试全部通过。
- 捕获 migration 和启动校验日志，确认不再出现 unregistered msgpack type warning。
- 在 Docker PostgreSQL、正式 FastAPI、真实 DeepSeek 请求中验证健康、账号、会话、SSE、run 成功、记忆跨重启与 G1 生命周期。
- 启动正式前后端，通过浏览器模拟用户完成注册或登录、记忆写入、对话运行、结果展示及清理路径验收，并检查关键响应式视口。
- 执行全量 pytest、Ruff、compileall、前端 build 和 Comet scope check；未运行项如实记录。
