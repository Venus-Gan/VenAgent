# G1 一跳召回排序完整目标规格

## 目标

VenAgent M05-G1 SHALL 在不降低长期记忆注入安全门槛的前提下，让已注册 `SIMILAR_TO` 一跳关系对最终召回产生有界、可解释且可复现的增益。PostgreSQL SHALL 是 settings、facts、sources、生命周期、authorization/deletion 围栏、单调 `authority_revision` 和 durable projection jobs 的权威存储；Neo4j SHALL 是 G1 唯一的持久化边存储，并以 `applied_revision` 表示已完整提交的图版本。G1 召回通过两个 revision、deletion generation、authorization epoch 和读前后复核组合跨存储快照，不得把跨库读取伪装成单事务原子快照。

## 候选与评分

- 普通事实继续按查询与权威事实文本的直接相关性产生种子和直接候选。
- `SIMILAR_TO` 邻居的路径相关性 SHALL 以“种子查询相关性 × 当前关系注册表相似度下界”计算；邻居有效相关性取自身直接相关性与所有合格一跳路径相关性的最大值。
- `FOLLOWS` 只表达来源时间线顺序，不单独提供语义相关性分数；其邻居只有自身直接相关性达到门槛时才可进入上下文。
- 图扩展只检查 seed 的直接邻边，禁止继续扩展邻居；任何 2-hop 或更深节点都不属于 M05 G1 候选。
- 图扩展候选仍须通过与直接候选相同的严格注入阈值。关系存在本身不得绕过相关性、授权、生命周期、来源、索引、有效期或预算检查。
- 同一次召回最多选择一个仅因图路径获得资格的邻居，总结果数不得超过调用方 `limit`。直接候选和图候选必须以稳定键确定性排序。
- 评分策略 SHALL 暴露稳定版本；阈值、关系注册表或评分公式发生语义变化时必须更新版本并重新验证。

## 一致召回快照

- `MemoryStore` SHALL 暴露权威 G1 recall snapshot application port，在一个 PostgreSQL 只读 `REPEATABLE READ` transaction snapshot 中返回同一 owner/tenant 下的 settings、facts、sources、deletion generation 和 `authority_revision`；它不返回 edges，也不接受 hop、路径评分或多跳预算参数。
- 独立 `MemoryGraphStore` SHALL 在同一个 Neo4j 只读事务快照中校验 projection state 并返回与 owner、tenant、`m05-g1-v1`、期望 `authority_revision` 和 deletion generation 完全匹配，且 `applied_revision` 已等于该权威 revision 的一批直接 seed 邻边；不得把 revision 检查与边查询拆成可竞态的两个 session，不得接受任意 hop 参数或返回部分 revision、旧 generation、非 seed 邻边或其他租户的边。
- application SHALL 先捕获权威 snapshot，再尝试读取匹配的 graph snapshot。若 Neo4j `applied_revision` 落后但 PostgreSQL snapshot 仍 current，application MAY 丢弃整批 edges 并使用该 snapshot 的普通直接事实。形成 `ContextBlock` 前 SHALL 重新验证当前 owner authorization epoch、deletion generation 和 `authority_revision`；任一权威值已变化、不匹配或不可验证时，本次 M05-L/G1 整批候选为空，不得返回 snapshot 中刚被删除、撤销或 supersede 的旧事实。
- 权威 settings/facts/sources snapshot 失败时，本次 M05-L/G1 候选全部为空。Neo4j 未配置、不可用、读取失败或围栏不匹配但权威 snapshot 可用时，application SHALL 使用空 edges 安全退化并更新 `memory-graph-g1` 的 disabled/degraded/pending 状态。
- non-durable graph test double SHALL 实现同一 graph port 与围栏语义，仅用于测试或明确的非持久运行；它不得成为 durable edge fallback。
- snapshot 与错误输出不得记录事实正文、原始来源内容、凭据、连接串或堆栈。

## 图投影与恢复

- `build_g1_edges` 继续由 application 根据 PostgreSQL 权威 facts/sources 生成完整目标边集合；Neo4j adapter 不拥有关系生成或召回评分规则。
- 所有会改变活动节点、边、来源资格或图生命周期的 PostgreSQL mutation SHALL 在同一权威事务内递增 owner/tenant `authority_revision` 并插入绑定该 revision 的 durable projection job；不得先提交事实再由 application 另行分配 revision/job。该契约 SHALL 覆盖 save/add-source/replace/forget/revoke-source/resolve-quarantine/expire/disable/enable/delete-all/owner-delete，不得保留旁路。
- 每次 owner/tenant 投影 SHALL 绑定目标 `authority_revision`、当前 deletion generation 和 `m05-g1-v1`。Neo4j adapter SHALL 先锁定/检查 owner/tenant projection state：目标 revision 小于已提交 `applied_revision` 时拒绝为 stale，等于时幂等 no-op，大于时才在同一写事务中停用旧活动边、upsert 当前节点壳与边，并在全部写入成功后提交新的 `applied_revision`；失败事务不得暴露半套新图。
- Neo4j `Memory` 节点 SHALL 只保存图定位与围栏所需的最小元数据，不保存事实正文、来源正文、可逆摘要或凭据。关系可保存 edge ID、已注册 relation、source 标识、active 状态、registry version、authority/applied revision、generation 与审计时间。
- PostgreSQL durable projection job SHALL 负责失败重试、running lease 恢复、重启恢复和 owner/tenant 冷重建。job 必须幂等并受 authorization epoch、deletion generation 与目标 `authority_revision` 围栏约束；每次 claim 必须具有 attempt/lease fence，过期 worker 不得 complete/retry 当前 job；旧 job 或旧 worker 不得停用、覆盖或复活新 revision。
- projection/purge/owner-cleanup SHALL 由应用 lifespan 管理的独立 memory maintenance consumer 推进，不依赖是否存在待执行 AgentRun。图类 job 在 Neo4j 暂时不可用时 SHALL 使用有上限的指数退避持续重试，直到成功、被更高 revision/generation supersede 或明确取消；不得在固定少量失败后永久停滞，也不得忙循环。
- Neo4j connection acquisition、transaction 和 query timeout SHALL 不超过 G1 provider/worker 的预算；只在外层取消 `to_thread` 不构成有效超时。长投影 SHALL 使用与硬超时协调的 lease 续期或足够 lease，并验证 timeout 后没有后台线程、session 或连接池占用泄漏。
- 长期事实 ready 与 graph ready SHALL 分离。事实持久化成功后，在满足既有资格与直接相关性门槛时可普通召回；图投影失败只影响 G1 图增益，不得把已持久化事实重新标记为不可用。
- owner 删除、记忆关闭、事实删除/过期/supersede 或最后有效来源撤销 SHALL 先通过 PostgreSQL 权威状态与 generation/revision 使旧图不可召回，再由 durable job 幂等清理 Neo4j 投影。

## 隔离与生命周期

- 图扩展只能发生在同一 owner、tenant 和当前关系注册表版本内。
- 删除、过期、superseded、quarantine、来源失效、事实索引未 ready 或 memory disabled 的事实不得作为种子、邻居或上下文块；graph projection pending 不得阻止合格事实作为普通直接候选。
- 权威长期事实或来源快照不可用时安全降级为无长期记忆；普通回答继续，并更新既有 memory health 状态。
- 图存储不可用但普通事实快照可用时安全降级为普通长期事实召回，并更新既有 graph health 状态。
- 事实失活后相关活动边立即在权威围栏上失效；Neo4j 清理可异步重试，但重启、旧 job 或注册表重放不得恢复指向非活动事实的召回。

## 评测

- 现有 `evals/memory` SHALL 对普通长期事实与 G1 1-hop 结果作可重放对照，分别报告 Recall@5、Precision@5、MRR、NDCG@5、HitRate@5、Context Precision、forbidden recall、duplicate rate 和 isolation failure rate，不用质量平均值掩盖安全失败。
- 回归数据与测试 SHALL 覆盖稳定排序、最多一个 graph-only 候选、FOLLOWS 不提供语义分、二跳不可达、owner/tenant 隔离、unknown registry、deleted/expired/superseded/quarantine、失效来源、索引未 ready、authorization epoch/deletion generation 变化和图降级。
- non-durable graph test double 与 Neo4j adapter SHALL 对同一冻结 edge fixture 产生等价 graph snapshot；PostgreSQL 权威 snapshot 与 Neo4j graph snapshot 的组合测试 SHALL 覆盖 authority/applied revision 匹配、图落后、请求末权威变化、重复/乱序 job、过期 claim token、超过 lease 的长投影、旧 worker fencing、自动恢复和 generation 漂移。没有真实 PostgreSQL/Neo4j 环境时必须如实标记对应集成检查未运行。
- M05 G1 评测不依赖 M05 G2 admission dataset、Gate A/Gate B、2-hop gold、LongMemEval 或生产数据授权目录。

## 非目标

- 本能力不实现或保留 M05 G2 多跳、实体图、自由本体、模型生成关系、path witness、admission report/hash、G2 capability/config、recursive CTE、G2 私有索引或新的外部检索依赖。
- 本能力不改变 `m05-g1-v1` 的 `FOLLOWS`/`SIMILAR_TO` 边生成语义，也不改变 `m05-g1-recall-v2` 的评分、注入阈值、总 limit 或 graph-only 上限；它只把 durable edge persistence 从 PostgreSQL 替换为 Neo4j 并调整必要的一致性端口。
- 文档知识图谱的 2-3 hop 检索属于 M08，不在 M05 或本 change 中实现。

## 验收

- 对照测试证明普通召回与 G1 召回在构造数据上产生一个可解释差异，且图扩展结果自身或路径有效相关性达到严格门槛。
- `FOLLOWS` 低相关邻居、二跳节点、跨 owner/tenant、旧注册表、失活事实和无效来源均不能进入上下文。
- 多个图邻居竞争时最多选择一个，结果总数、排序和重复执行保持稳定。
- 并发修改不能让一次召回使用 `applied_revision` 与 snapshot `authority_revision` 或 generation 不匹配的 edges；请求末 authorization epoch/deletion generation/authority revision 失效时整批长期候选为空，只有 Neo4j 单纯落后且权威 snapshot 始终 current 时安全退化为普通事实。
- 真实 PostgreSQL + Neo4j 集成证明冷重建、单事务替换、失败降级、durable job 恢复、重启、删除和 replay 保持生命周期正确；活动代码和 schema 不再读取、写入或要求 `memory_edges`。
