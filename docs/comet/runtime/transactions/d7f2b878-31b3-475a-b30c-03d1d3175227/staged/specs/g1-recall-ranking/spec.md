# G1 一跳召回排序完整目标规格

## 目标

VenAgent M05-G1 SHALL 在不降低长期记忆注入安全门槛的前提下，让已注册 `SIMILAR_TO` 一跳关系对最终召回产生有界、可解释且可复现的增益。G1 召回使用一致的权威 memory 数据快照，并在投影前复核授权 epoch 与删除 generation，避免并发变化导致跨时点拼接或失效数据注入。

## 候选与评分

- 普通事实继续按查询与权威事实文本的直接相关性产生种子和直接候选。
- `SIMILAR_TO` 邻居的路径相关性 SHALL 以“种子查询相关性 × 当前关系注册表相似度下界”计算；邻居有效相关性取自身直接相关性与所有合格一跳路径相关性的最大值。
- `FOLLOWS` 只表达来源时间线顺序，不单独提供语义相关性分数；其邻居只有自身直接相关性达到门槛时才可进入上下文。
- 图扩展只检查 seed 的直接邻边，禁止继续扩展邻居；任何 2-hop 或更深节点都不属于 M05 G1 候选。
- 图扩展候选仍须通过与直接候选相同的严格注入阈值。关系存在本身不得绕过相关性、授权、生命周期、来源、索引、有效期或预算检查。
- 同一次召回最多选择一个仅因图路径获得资格的邻居，总结果数不得超过调用方 `limit`。直接候选和图候选必须以稳定键确定性排序。
- 评分策略 SHALL 暴露稳定版本；阈值、关系注册表或评分公式发生语义变化时必须更新版本并重新验证。

## 一致召回快照

- `MemoryStore` SHALL 暴露 G1 recall snapshot application port，一次返回同一 owner/tenant 下的 memory settings、facts、sources 与当前关系注册表 edges；port 不接受 hop、路径评分或多跳预算参数。
- temporary adapter SHALL 在共享 `RLock` 的一次持有期间复制完整 recall snapshot；不得通过多次锁获取拼接 facts、sources 与 edges。
- PostgreSQL adapter SHALL 在一个只读 `REPEATABLE READ` transaction snapshot 中读取 settings、facts、sources 与 edges；不得通过独立 autocommit 查询拼接，不需要 recursive CTE。
- application SHALL 把 recall snapshot 与本次 `MemoryRequestSnapshot` 的 owner、tenant 和 deletion generation 对齐，并在形成 `ContextBlock` 前再次验证当前 owner authorization epoch 与 deletion generation。任一不匹配、不可验证或权威 facts/sources snapshot 失败时，本次 M05-L/G1 候选全部为空。
- 图边读取失败但权威 facts/sources 已形成一致快照时，application MAY 使用空 edges 安全退化为普通长期事实召回，并把 `memory-graph-g1` 更新为 degraded；不得返回部分边集合或伪造 G1 结果。
- snapshot 与错误输出不得记录事实正文、原始来源内容、凭据、连接串或堆栈。

## 隔离与生命周期

- 图扩展只能发生在同一 owner、tenant 和当前关系注册表版本内。
- 删除、过期、superseded、quarantine、来源失效、索引未 ready 或 memory disabled 的事实不得作为种子、邻居或上下文块。
- 权威长期事实或来源快照不可用时安全降级为无长期记忆；普通回答继续，并更新既有 memory health 状态。
- 图存储不可用但普通事实快照可用时安全降级为普通长期事实召回，并更新既有 graph health 状态。
- 事实失活后相关活动边立即失效；重启或注册表重放不得恢复指向非活动事实的召回。

## 评测

- 现有 `evals/memory` SHALL 对普通长期事实与 G1 1-hop 结果作可重放对照，分别报告 Recall@5、Precision@5、MRR、NDCG@5、HitRate@5、Context Precision、forbidden recall、duplicate rate 和 isolation failure rate，不用质量平均值掩盖安全失败。
- 回归数据与测试 SHALL 覆盖稳定排序、最多一个 graph-only 候选、FOLLOWS 不提供语义分、二跳不可达、owner/tenant 隔离、unknown registry、deleted/expired/superseded/quarantine、失效来源、索引未 ready、authorization epoch/deletion generation 变化和图降级。
- temporary 与 PostgreSQL SHALL 对同一冻结 fixture 产生等价 snapshot 与召回结果；没有真实 PostgreSQL 环境时必须如实标记该集成检查未运行。
- M05 G1 评测不依赖 M05 G2 admission dataset、Gate A/Gate B、2-hop gold、LongMemEval 或生产数据授权目录。

## 非目标

- 本能力不实现或保留 M05 G2 多跳、实体图、自由本体、模型生成关系、path witness、admission report/hash、G2 capability/config、recursive CTE、G2 私有索引或新的外部检索依赖。
- 本能力不改变 `m05-g1-v1` 的 `FOLLOWS`/`SIMILAR_TO` 边生成语义和持久化结构，也不改变 `m05-g1-recall-v2` 的评分、注入阈值、总 limit 或 graph-only 上限。
- 文档知识图谱的 2-3 hop 检索属于 M08，不在 M05 或本 change 中实现。

## 验收

- 对照测试证明普通召回与 G1 召回在构造数据上产生一个可解释差异，且图扩展结果自身或路径有效相关性达到严格门槛。
- `FOLLOWS` 低相关邻居、二跳节点、跨 owner/tenant、旧注册表、失活事实和无效来源均不能进入上下文。
- 多个图邻居竞争时最多选择一个，结果总数、排序和重复执行保持稳定。
- 并发修改不能让一次召回混合不同时点的 facts、sources 与 edges；epoch/generation 失效时整批候选为空。
- temporary 与真实 PostgreSQL adapter 的 snapshot/结果一致；重启、删除和 replay 后保持生命周期正确。
