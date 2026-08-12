# Outcome

在不推翻当前 feature-first 目录和 M05 权威治理边界的前提下，完成可用于日常对话的语义记忆链路：用户自然陈述的稳定事实可以安全提取、跨 conversation 召回、明确纠正并可追溯治理；提取、索引、图投影和模型故障均返回真实降级结果，不污染事实或伪造命令成功。

本 change 将当前已发现的正确性缺陷、结构化 LLM 提取、embedding 召回、冲突治理、旧数据迁移、健康状态、HTTP/前端错误反馈和真实用户验收合并为一个交付单元。

# Scope

- 修复问题/否定/假设/引用被规则误识别为事实、弱候选隐式覆盖旧事实、显式写入成功后返回 500、非 JSON 错误响应和虚假 memory READY 状态。
- 将自动提取改为回答发布后的 durable extraction job；worker 使用结构化 extractor，确定性 policy 负责来源、主体、敏感信息、陈述模式、时态、动作和生命周期门控。
- 引入 `ADD`、`UPDATE`、`NOOP`、`QUARANTINE` 的长期事实合并语义；LLM conflict judge 只处理模糊候选并提出建议，不能直接修改权威事实。
- 增加独立的 embedding/index 派生投影、版本化阈值、slot 精确召回、embedding 召回、可评测词法降级和 G1 1-hop 重建；事实权威仍属于 PostgreSQL，Neo4j 仍只保存图元数据。
- 保持短期完整 turn、来源范围、摘要校验和失败回退；在同一 change 内接入可选语义 `SummaryBuilder`，不可用时回退确定性摘要或最近完整 turn。
- 增加 extractor、embedding、index、graph 的独立健康状态和运行时状态转移；provider 失败只省略对应派生层，不阻塞普通回答。
- 当前项目尚未上线，本 change 不保留或迁移既有开发期记忆数据；通过显式、可重复执行的开发期清理/重建步骤删除旧事实、来源、摘要、任务、索引和图投影，再按新契约生成数据。
- 扩展 M05 application port、temporary/PostgreSQL memory adapter、迁移、memory jobs、promptctx block metadata 和配置装配；不新增专用记忆页面或未来 M06-M09 空壳。

# Non-goals

- 不持久化用户 preference/personality，不从 assistant 自由文本直接生成长期事实。
- 不建设 M05 episodic memory、TaskMem、实体事实图、2-hop 或更深个人记忆遍历；个人任务 episode 由未来 M07 独立 Shape，文档多跳由 M08 负责。
- 不复制 AGI-saber 的 Go package、表结构、内存/数据库双权威、进程 goroutine 或 importance/统一 TTL 聚合策略。
- 不把 embedding index 或 Neo4j 投影提升为事实权威，不改变现有 owner/tenant、授权 epoch、deletion generation、来源撤销和删除确认语义。

# Acceptance examples

- `记住，我叫小维` 在权威事实提交成功后返回稳定成功结果；派生 graph/index 失败只能显示 pending/degraded，不返回 500。
- 普通对话中的 `我叫小维` 进入异步提取并在新 conversation 的 `我叫什么？` 中按 name slot 或语义召回；问题句 `我叫什么` 不产生事实。
- `我不叫小维`、`如果我叫小维`、`小王说“我叫小维”` 不会产生 `name=小维` 的 owner 事实。
- `我改名叫阿维` 唯一纠正当前姓名并 supersede 旧事实；`我以前叫小维` 不覆盖当前姓名；无法判断时进入 quarantine。
- embedding provider 不可用时，slot 精确路径仍可用，普通 embedding 召回为空并报告 degraded；词法回退只有在版本化评测通过时启用。
- 删除、撤销来源、过期、quarantine、旧 generation 和其他 owner 的事实均不得进入 promptctx ContextBlock 或 G1 扩展。
- LLM、embedding、PostgreSQL、Neo4j 任一派生能力故障时，普通回答完成，`/memory status` 显示正确组件、reason code、pending/failed 状态。
- 浏览器完成注册、写入、刷新、新 conversation 回忆、更新、忘记、关闭/启用和删除全过程；所有失败响应可被前端稳定解析。

# Constraints and invariants

- `venagent/memory/` 持有事实、policy、合并、授权、生命周期、job、召回和排序；`promptctx/` 只持有 ContextBlock 和最终投影；`llm/` 只提供通用模型/embedding adapter；`repo/` 只实现 port。
- LLM 只能提出结构化候选或冲突建议；确定性 policy 是秘密禁存、特殊类别、owner/tenant、来源、删除、有效期和 quarantine 的最终权威。
- 权威事实先事务提交，embedding/index/Neo4j 是可重放的异步投影；派生失败不能回滚已确认的事实，也不能让旧 generation 复活。
- 所有请求和后台 job 绑定 owner、tenant、authorization epoch、deletion generation、source_ref、policy/extractor/index version。
- embedding 向量、原始输入、LLM 原始响应和敏感事实不得进入日志、普通错误响应或未授权上下文。
- 自动抽取只接受原始用户消息及未来明确授权的工具结果；assistant 文本、摘要和最终 prompt 没有长期来源资格。
- 新增或修改的行为必须有正常、失败、边界、隔离、删除和降级测试，并有真实浏览器操作证据；未运行的 LLM/压力/外部安全检查如实记录。

# Decisions

- 保留现有 `MemoryService` façade 和显式组合，不重新引入 mixin 或聚合 service。
- 保留 `promptctx/recall_provider.py` 的纯 ContextBlock 转换职责，不让其承担提取、授权、排序或外部 I/O。
- 采用 slot 精确召回 + embedding 语义召回 + 经过评测的 lexical fallback + G1 1-hop；首版不加入 LLM reranker 或个人多跳推理。
- 采用 durable extraction/index/project jobs；不使用 AGI-saber 的进程 goroutine 作为可靠任务机制。
- 结构化记忆提取默认复用当前对话模型；允许通过仓库根 `.env`/进程环境的 `MEMORY_EXTRACTOR_*` 白名单配置覆盖为低成本模型或独立 provider。仅配置 extractor model 时继承主模型连接配置；显式配置独立 provider 时按完整 profile 严格校验。调用失败或输出不合法时只让自动提取能力进入可观测降级，不阻塞普通回答。
- M05 首版 embedding 派生索引继续使用现有 PostgreSQL，以 `real[]` 保存向量并在 owner 范围内执行应用层余弦计算；本 change 不更换 Compose PostgreSQL 镜像或引入 pgvector。
- embedding 使用通用 `EMBEDDING_API_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL` 配置，不使用 `MEMORY_EMBEDDING_*`。M05 首先消费该技术 adapter，未来 M08 RAG 复用相同配置和 embedding port；本 change 不预建 M08 目录或业务逻辑。三项全部缺失时 embedding/index 明确 disabled，部分配置快速失败，不回退 chat model 或伪造向量。
- 当前项目未上线，旧开发期记忆数据全部删除，不实施 source_ref 重放、旧事实 quarantine 或兼容迁移；清理不得影响 owner、conversation、run 等非记忆业务数据。
- 记忆自动提取、embedding 和 graph/index 健康状态独立呈现；缺少可选 provider 时安全降级，不虚报完整 READY。
- 用户已确认本 brief 与四份完整目标规格共同定义的 M05 交付契约，同意按上述范围、关键决定、验收标准和非目标进入 Build。

## M05 intake 与 AGI-saber 代码对照

- 对照基线：VenAgent `acdd29627e998b734896d6662d0a674cc550311b`；本机 AGI-saber `fead7687a82965b3c0106728089ccde0cc0eb3e8`。研究范围为两仓当前 memory、promptctx、chat 写入、持久化和测试路径；没有把 AGI-saber 的 Go 目录或表结构当作迁移模板。
- Search-first 结论：Extend 现有 `MemoryService`、durable jobs、PostgreSQL/Neo4j authority fencing 和 `promptctx` 投影；Compose 现有 LLM factory 与新增 M05 model adapter；Build 缺失的 extractor/conflict/index 行为；不引入新的 memory 框架或向量数据库。

| AGI-saber 静态证据 | 观察到的实际行为 | VenAgent 当前缺口 | 本 change 取舍与落点 |
|---|---|---|---|
| `internal/application/chat/mem_writer.go` | 用户消息经 LLM JSON 抽取、分类、生成 embedding 后写入；同时也从 assistant 回答派生事实 | `long_term/policy.py` 仅靠正则，问题/否定/假设会误命中；没有结构化 extractor 或 embedding 生成 | Adopt 抽取与 embedding 能力，Extend 为严格 schema + 原文 source span + durable job；拒绝 assistant 派生。落到 `long_term/extractor.py`、`jobs.py`、`llm/memory.py` |
| `internal/domain/memory/longterm/longterm.go` | embedding 余弦优先，缺失时使用自建 TF 词袋；按 category/user 过滤并混入 importance | `memory/recall.py` 只有二元 n-gram Jaccard，真实问法低于门槛 | Adopt 语义召回和 slot 过滤；Extend 为 slot 精确 + owner 范围 cosine + 评测准入词法回退；不复制 TF、固定权重和 importance 排序。落到 `memory/index.py`、`recall.py` |
| `internal/domain/memory/longterm/longterm.go::ConflictCandidates` 与 `internal/application/chat/conflict.go` | embedding 提名同类模糊候选，LLM judge 判断对立后直接 supersede | `writer.py` 发现同 slot 不同内容就直接替换，弱候选会覆盖旧事实 | Adopt 候选提名 + LLM judge；Extend 为 slot 优先、judge 只建议、policy 最终决定 `ADD/UPDATE/NOOP/QUARANTINE`。落到 `long_term/conflict.py`、`writer.py` |
| `internal/application/chat/mem_stack.go` 与 `infrastructure/persistence/longterm/longterm.go` | 进程内 LTM/Preference 与 PostgreSQL write-through 双写并同步 ID | VenAgent 已有 PostgreSQL authority/revision/job，不需要第二份 durable 事实 | Reject 双权威与 lazy hydrate；PostgreSQL 继续是唯一 durable facts/sources/lifecycle 权威，temporary 仅用于测试/非持久模式 |
| `internal/domain/memory/graph/graphmem.go` | 写入时 goroutine 更新 Neo4j，节点复制正文，可扩展图邻居，Neo4j 缺失时退化 LTM | VenAgent 已有 G1 revision/generation fencing，但 embedding/index 尚未接入同一恢复链 | Adopt 图增强可降级；Extend 为 PostgreSQL 事务内 revision + durable projection job、Neo4j 最小元数据、固定 1-hop；拒绝裸 goroutine、正文复制和任意 hops |
| `internal/domain/promptctx/source_recall.go` 与 `assembler.go` | recall source 转为 slot item，再按槽位和全局预算裁剪 | VenAgent 已有纯 `ContextBlock` 投影，但 recall metadata 与分层健康证据不足 | Extend 现有 `promptctx/recall_provider.py`，只增加已过滤候选的来源/评分元数据；不把提取、排序、授权或 I/O 移入 `promptctx/` |
| `mem_writer.go`、`memory/preference` | preference 被跨会话保存；assistant 问答可形成长期事实 | 与 VenAgent 已确认的 preference 禁存、user/tool source-only 契约冲突 | Reject；相关测试必须证明 preference 和 assistant 文本不会进入 fact、index、graph 或 ContextBlock |
| `longterm.go::Consolidate` | importance 衰减、统一 TTL、内容拼接合并，图中心性可保护条目 | 会把不同有效期和强制删除语义混在启发式分数中 | Reject 固定衰减/统一 TTL/内容拼接；沿用 `valid_until`、来源撤销、superseded、quarantine、deletion generation 等显式生命周期 |

# Open questions

- 无。

# Verification expectations

- 运行 M05 相关 pytest、完整 pytest、Ruff、compileall、PostgreSQL/Neo4j 集成测试和 Comet scoped text check。
- 使用固定结构化 fake LLM/embedding 覆盖 extraction、解析失败、超时、冲突、重试和幂等；真实 provider 测试只在真实配置可用时运行并记录结果。
- 扩展 `evals/memory/` 至包含陈述/问题/否定/假设/引用/纠正/TTL/删除/跨 owner/故障时间线，而不是只验证规则函数。
- 使用浏览器模拟至少一条跨 conversation 记忆流程和一条故障/降级流程，证明用户可见结果、刷新持久化和错误反馈一致。
- Verify 必须单独报告事实存储成功、embedding/index pending、G1 graph pending、普通事实召回和最终 ContextBlock 注入，不能用总 READY 替代分层证据。
