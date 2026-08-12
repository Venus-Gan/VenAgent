# Outcome

将 Neo4j 设为 M05 `GraphMemory` 唯一的持久化边存储，同时保持已经冻结的 G1 1-hop 产品行为、安全门槛和模块边界。PostgreSQL 继续作为长期事实、来源、owner 记忆设置、生命周期、授权/删除 generation 与持久任务的权威存储；它不再保存、读取或回退提供 `memory_edges`。

这不是单纯把 `memory_edges` 表换成 Neo4j 表达。重构必须把权威事实端口与图投影端口分离，并以 projection revision、deletion generation 和 authorization epoch 围栏替代当前 PostgreSQL 单事务内的 facts/sources/edges 快照，确保跨存储召回不会组合不一致或已失效的数据。

# Scope

- 拆分 M05 application port：权威 memory store 继续负责 settings/facts/sources/lifecycle/jobs，独立的 G1 graph store 负责 Neo4j 节点壳、关系边、owner/tenant 图投影版本与清理。
- 新增 M05 专属 Neo4j adapter、配置、连接生命周期、健康映射和 composition-root wiring；M05 与未来 M08 只共享平台级 driver/runtime，不共享 adapter、label、关系注册表或查询入口。
- 新增独立 `GraphMemory` application service，作为 M05 长期事实与图存储之间的能力边界；`MemoryService` 稳定 façade 委托给它，maintenance worker 只负责 job 调度并调用 GraphMemory，不拥有图业务规则。
- 将 G1 召回改为先取得 PostgreSQL 权威快照，再读取与同一 owner/tenant、registry version、projection revision 和 deletion generation 匹配的 Neo4j 一跳边；任一围栏不匹配时忽略整批图边并退化为普通长期事实召回。
- 为每个 owner/tenant 维护单调 `authority_revision`：所有会改变活动节点、边或来源资格的 PostgreSQL mutation 必须在同一权威事务内递增 revision 并插入对应 durable projection job，消除“事实已提交但 revision/job 尚未落库”的崩溃窗口。
- 保留 `build_g1_edges` 的确定性业务规则；按 owner/tenant 生成完整目标图，并在一个 Neo4j 写事务中停用旧活动边、upsert 当前节点/边和提交新的 projection revision。
- Neo4j 投影以 `applied_revision` 作 compare-and-set：并发或乱序 worker 必须在修改图前拒绝旧 revision，同 revision 重放幂等 no-op，新 revision 不得被旧 job 覆盖。
- 将图投影与长期事实可用状态解耦：事实成功持久化后可按直接相关性召回；Neo4j 投影失败只使 G1 graph pending/degraded，并由 PostgreSQL 中的 durable projection job 重试。
- 将 projection/purge job 消费从 agent run 调度器中拆为应用生命周期内的独立 memory maintenance 职责；即使没有新 run、只有管理命令或 Neo4j 恢复，也必须持续收敛，并保留多进程 lease 竞争语义。
- 把事实删除、来源撤销、过期、supersede、owner 删除和 `/memory disable` 接入跨存储 fencing 与可重试图清理；权威状态先使旧图不可召回，Neo4j 物理清理由后台完成。
- 移除 PostgreSQL 图 adapter、运行期 `memory_edges` 读写和 schema 必需项；调整 temporary test double、配置、迁移、健康状态、测试与 canonical 规格。

# Non-goals

- 不改变 `m05-g1-v1` 的 `FOLLOWS`/`SIMILAR_TO` 生成规则、边方向、相似阈值或关系注册表。
- 不改变 `m05-g1-recall-v2` 的 seed、评分、严格注入阈值、稳定排序、总 limit 或最多一个 graph-only 候选。
- 不实现 2-hop 或更深遍历、实体图、自由本体、模型生成关系、图中心性保护或 M05 G2。
- 不实现 M08 RAG/知识图谱，不复用 M08 的 label、schema、adapter 或查询；本 change 只为未来共享同一个 Neo4j 平台连接保留装配边界。
- 不升级 embedding、候选提取、事实冲突策略、HTTP/命令表面或 Vue UI。
- 不照搬 AGI-saber 的 Go 包结构、异步 goroutine、整数 ID、节点属性或 Cypher；它只作为 GraphMemory/KGStore 分界和降级行为的事实依据。

# Acceptance examples

- 给定同一冻结 fixture，投影完成后的 Neo4j G1 召回与当前 PostgreSQL G1 召回产生相同的合格候选、最多一个 graph-only 候选和稳定排序；二跳节点仍不可达。
- Neo4j 未配置时，durable 应用仍可启动并提供 PostgreSQL 普通长期事实召回，`memory-graph-g1` 为 disabled；Neo4j 已配置但连接、读取或写入失败时，普通长期事实继续，图能力为 degraded/pending，错误不泄漏连接信息。
- 一条事实已写入 PostgreSQL但 Neo4j 投影失败时，该事实在满足既有安全与直接相关性门槛后仍可普通召回；恢复 Neo4j 并处理 durable projection job 后，一跳图增益自动恢复。
- 即使系统没有待执行 agent run，独立 memory maintenance 仍会领取到期 projection/purge job；单轮 Neo4j 故障会记录可净化的错误、退避并继续重试，不能被静默吞掉或使主应用退出。
- PostgreSQL 权威快照 revision/generation 与 Neo4j 图快照不匹配时，本次只使用权威 facts/sources，不返回任何旧图邻居；投影完成且围栏匹配后才恢复图扩展。
- 若 Neo4j 只是落后于本次 PostgreSQL `authority_revision`，本次可以使用同一权威快照中的普通直接事实而不使用图；若请求结束前 PostgreSQL `authority_revision`、authorization epoch 或 deletion generation 已变化，则整批长期事实与图候选都为空，不能返回刚被删除、撤销或 supersede 的旧快照事实。
- 任一图影响 mutation 成功后，即使进程在返回前崩溃，PostgreSQL 中也同时存在更高 `authority_revision` 与对应 projection job；重启后能够自动收敛，不能留下“旧图仍被误判为 current”的永久窗口。
- 到期扫描、来源撤销、事实 supersede/forget、启停、delete-all 与账号删除等非主写入路径也遵守相同原子契约；不存在只更新 PostgreSQL 权威状态却不递增 revision/插入 job 的旁路。
- 当 revision N 与 N+1 的 projection job 并发或乱序执行时，N+1 一旦提交，N 只能 no-op/取消，不能停用或覆盖 N+1 的节点、边与 `applied_revision`。
- owner 删除、记忆关闭、事实删除/过期/supersede 或最后有效来源撤销发生后，即使 Neo4j 暂时不可用，旧节点/边也不能再次进入召回；恢复后后台清理收敛。
- 同一 owner/tenant 的完整目标图在单个 Neo4j 写事务内替换；失败时旧 committed revision 不会被标记为新 revision，读取方不会看到半套新图。
- 活动运行时代码与 schema 校验不再查询、写入或要求 `memory_edges`；不存在 PostgreSQL edge read fallback 或双写路径。
- M05 `Memory` 节点/关系与未来 M08 `Entity`/文档关系即使使用同一 Neo4j 实例，也通过独立 label、约束、adapter 与查询保持隔离。

# Constraints and invariants

- PostgreSQL 始终是事实正文、来源、设置、生命周期、授权 epoch、删除 generation 和 durable job 的唯一权威；Neo4j 数据始终是可重建投影，不得反向修改权威事实。
- Neo4j 是 M05 唯一的 durable edge store。允许保留显式的 non-durable test double，但不得存在 PostgreSQL/file/in-memory 的生产 edge fallback 或 shadow dual-write。
- 跨 PostgreSQL 与 Neo4j 不伪装成分布式原子事务；一致性由单库事务、projection revision/generation fencing、读前后复核和失败时整批丢弃图边实现。
- `authority_revision` 由 PostgreSQL 权威事务单调分配，`applied_revision` 只表示 Neo4j 已完整提交的投影。两者名称、所有权和比较方向不得混用；revision 不得仅存在于进程内，也不得从时间戳推断。
- 所有 Neo4j 读写必须强制 owner/tenant 隔离，关系类型只允许注册表中的 `FOLLOWS` 与 `SIMILAR_TO`，不能把未校验字符串拼成 Cypher 关系类型。
- 仓库 `final/internal/platform/neo4j.py` 与 `final/internal/memory/graph_memory.py` 是旧运行时反例，不得导入或复用：其全局 `Memory.mem_id`、正文复制、动态 hop、daemon thread、启动期静默 DDL、错误转空集合和 URI/异常日志均不满足当前 owner/tenant、安全、事务与可观测性契约。
- M05 Neo4j label、constraint/index 名称和 projection-state identity 必须带模块命名空间；节点唯一身份至少包含 owner、tenant、memory ID，不能依赖全局整数/进程 hash。M08 共享 driver 时不得因通用 `Memory`/`Entity` label 或约束名碰撞而互相读写。
- Neo4j 由根 `compose.yaml` 中与 PostgreSQL 并列的独立服务提供，使用固定受支持版本的官方镜像、独立持久 volume、Bolt/HTTP 可配置宿主端口、健康检查与 `restart: unless-stopped`。不得使用浮动 `latest`、提交真实/通用默认密码或为了本 change 引入 APOC/Graph Data Science 等插件。
- Compose Neo4j 健康只代表基础设施可连接；应用仍按严格配置和 schema version 单独验证。Neo4j 容器未启动、未配置或不可达不得使 PostgreSQL durable runtime 降为 temporary，也不得阻止普通长期事实召回。
- 配置命名沿用现有白名单模式：应用读取 `NEO4J__ENABLED`、`NEO4J__URI`、`NEO4J__DATABASE`、`NEO4J__USER` 与秘密变量 `NEO4J_PASSWORD`；Compose 端口使用 `NEO4J_BOLT_PORT`/`NEO4J_HTTP_PORT`，数据卷固定命名为 `venagent-neo4j-data`。连接池大小和 acquisition/query/transaction timeout 也必须进入严格类型配置，不允许从任意宿主环境透传未知字段。
- 本地标准启动为 `docker compose up -d postgres neo4j`。应用仍运行在宿主机时，示例 URI 指向可配置的本地 Bolt 映射端口；未来若应用容器化再单独调整为 Compose service DNS，不在本 change 预建 app container。
- Neo4j schema/constraint 采用显式、可重复的 graph migration/bootstrap 命令，应用启动只在有界 deadline 内验证兼容性与连接，不执行或静默忽略 DDL。PostgreSQL schema migration 不调用 Neo4j 网络，也不把两套迁移伪装成原子操作。
- G1 图只接受 application 已构建并校验的完整边集合；Neo4j adapter 不拥有边生成、召回评分或事实生命周期业务规则。
- 事实失活的安全效果先由 PostgreSQL 权威状态与 generation/revision fence 生效，不依赖 Neo4j 清理成功；清理任务必须幂等、可重试且不能复活旧 revision。
- inactive/versioned edge audit 继续由图投影保存，但任何非当前 revision、非活动或 registry 不匹配的边都不得参与召回。
- “inactive/versioned edge audit”按当前行为保持为每个确定性 edge ID 最多一条关系，记录最近活动/失活 revision 与时间；不为每次 projection 复制整套历史图。即便如此，历史 memory ID 形成的 inactive 关系仍可能增长，Build 必须报告 owner 级 active/inactive 数量并由 delete-all/account cleanup 清除；独立长期保留策略不在本 change 偷加。
- 读取 deadline 不能只依赖 `asyncio.wait_for(asyncio.to_thread(...))`，因为超时不会终止底层阻塞查询；Neo4j connection acquisition、transaction/query timeout 必须有界且不大于 provider 预算，超时后的后台线程不得持续占用连接池形成级联耗尽。
- 当前 `build_g1_edges` 对 owner/tenant 活动事实执行全量两两比较，复杂度为 O(n^2)；本 change 不改变算法，但 Build 必须对冷重建和单事务参数体积做有界批处理/基准验证，并把超大 owner 无法收敛作为显式剩余风险，不能用静默截断改变图语义。
- 当前 production consumer 只在 `AgentRuntime._worker_loop` 顺带调用 `process_pending_jobs`，把图收敛错误地绑定到 run 调度；而异常被直接吞掉。Build 必须迁移到受 lifespan 管理的独立 memory maintenance loop，具有有界批量、lease/retry/backoff、错误净化日志/健康状态和干净 shutdown，且不能由每个 worker 无界并发重建同一 owner 图。
- 当前 job lease 固定为 30 秒，claim 与 complete/retry 只按 `job_id` 更新，没有 attempt/claim token。全量 O(n^2) 构图或 Neo4j 写入超过 lease 后，旧 worker 仍能覆盖新 worker 的终态。Build 必须为每次 claim 生成 fence token（或等价 lease version），complete/retry/cancel 只能由仍持有 lease 的 worker 提交，并对长任务续租或设置与 lease 协调的硬超时。
- 当前 projection job 最多尝试 3 次后永久 `failed`，而用户表面没有 replay 命令；这与“Neo4j 恢复后自动收敛”冲突。Graph projection 与 purge/owner cleanup 必须使用可持续的有界指数退避，直到被更高 revision/generation supersede、明确取消或成功；不能忙循环，也不能因短暂故障永久停止。事实提取等非图 job 保留既有失败策略。
- 当前 `expire_due()` 一次跨 owner 批量失活事实并直接更新 PostgreSQL `memory_edges`，不插入 projection job。迁移后到期处理必须按受影响 owner/tenant 分组，在 PostgreSQL 事务中递增各自 revision 并插入 job；大批到期需有界分批，不能形成无界事务或漏投影。
- job claim 当前只接受 lifecycle 为 `active` 的 owner；采用保留 `deleting` tombstone 后，cleanup/purge job 必须有受限的删除态领取规则，否则 owner 会永久卡在 deleting。该规则只允许清理，不能重新执行 extraction/project 写入或恢复召回。
- 当前 `MemoryHealth` 与 `/memory status` 只有 `index_pending`，并把任何 pending/failed job 与事实索引未就绪混在一起；这与已确认的“fact ready、graph pending”语义冲突。不得继续用 fact `index_status` 表示 Neo4j projection 状态，现有命令必须增加独立 graph pending/failed/reason 表达。
- 当前自然语言“记住”、`/memory update` 与 `/memory show` 也把图投影描述为“派生索引”，且声称同步前不会自动召回；这些文本必须统一修正，明确事实已可用而 G1 图可能待同步，不能只改 status 聚合数。
- 当前 `StartupReport` 在 composition 时冻结，而 Neo4j 的真实连接结果只能在 driver open/verify connectivity 后得知。Build 必须让启动日志记录 open 后的 graph 状态，运行时 `/health` 继续使用动态 capability registry；Neo4j 故障不得把 PostgreSQL durable runtime 替换为 temporary runtime。
- Neo4j driver 配置必须使用严格字段、SecretStr/等价秘密封装、显式 database、连接池上限、TLS/证书策略和 acquisition/query/transaction deadline；日志与 health 不得回显 URI、用户名、密码、Cypher 参数、事实正文或原始 driver 异常。
- account 删除当前会在 conversations 清空后直接删除 PostgreSQL owner，并通过 FK cascade 删除 memory jobs；若 Neo4j 清理未先完成会留下无 durable job 可追踪的孤立图。Build 必须先保留不可访问的最小 `deleting` owner/tombstone，待 Neo4j owner graph 清理成功后才物理删除 owner。
- account 删除一经权威事务接受，事实/来源正文和摘要必须立即失活、清空或进入既有删除流程，authorization epoch/generation 立即封锁召回；为清理 Neo4j 保留的 tombstone 只能含 owner/tenant、generation/revision、job 与审计时间等最小元数据。Neo4j 故障只能延迟物理图清理，不能延迟用户不可访问语义。
- Neo4j 节点 ID 与关系元数据即使不含正文仍属于需要删除治理的用户关联数据；运行库清理完成不等于备份介质立即擦除，部署文档必须明确 Neo4j 备份保留/过期与删除 SLA，这一外部备份策略作为运维责任如实记录。
- 当前 schema migration 在版本升级时重建 owners/conversations/runs/memory 全部表；它与“保留 PostgreSQL 权威 facts 后冷重建 Neo4j”冲突。本 change 必须改为保留 owners、conversations、runs、checkpoints、memory facts/sources/jobs 的 forward migration。
- 现有 active fact 的 `index_status=pending/failed` 表达旧 PostgreSQL edge 投影状态，旧 `project` job 也没有目标 revision/claim fence；forward migration 不能原样继承这些语义。迁移必须保持事实/来源与非图 job 的业务含义，归一化旧图耦合状态，取消/转换旧 project job，并按 owner/tenant 原子建立初始 `authority_revision` 与一条可幂等冷重建 job。
- `authority_revision` 的作用域是 owner/tenant，而当前 `memory_settings` 只有 owner 维度；实现不能为省表把未来不同 tenant 共用一个模糊 revision。应使用明确的 owner/tenant projection authority record（或等价复合键），同时让 owner 级 deletion generation 对全部 tenant 形成更高层围栏。
- 现有 dirty worktree 中与本 change 无关的用户修改保持不动。

# Decisions

- 已确认：Neo4j 是 M05 `GraphMemory` 唯一的持久化边存储；PostgreSQL 不作为 edge fallback。
- 已确认：保持 AGI-saber 的模块边界，M05 只负责记忆条目图与严格 G1 1-hop；M08 文档知识图谱保持独立。
- 已确认：本 change 是存储架构重构，不新增图算法能力；为了真正完成替换，可以调整 port、snapshot、job、wiring、配置、迁移和测试。
- 已确认：图投影按 owner/tenant 全量确定性重建，并在一个 Neo4j 事务中替换；不采用逐边跨事务写入作为完成语义。
- 已确认：以 projection revision/deletion generation fencing 处理跨存储一致性，使用 PostgreSQL durable jobs 重试；事实 ready 与 graph ready 分离。
- 已确认：M05 与 M08 只共享 Neo4j 平台 driver/runtime，分别拥有 schema/label、adapter、查询和生命周期。
- 已确认：最终移除 `memory_edges`，不保留可执行的 PostgreSQL 边读取、写入、回退或双写路径。
- 已确认：embedding、图中心性、M08、多跳和关系注册表变化不在本 change。
- 已确认（Q1=A）：Neo4j `Memory` 节点只保存 memory ID、owner/tenant、registry/projection revision、deletion generation 等图定位与围栏最小元数据；不复制事实正文、来源正文或可逆摘要。
- 已确认（Q2=A）：不迁移旧 `memory_edges`、不双写或保留只读过渡表；直接从 PostgreSQL 权威 facts/sources 冷重建 Neo4j 图，并在本 change 移除 PostgreSQL 边表及全部运行期依赖。重建完成前 G1 降级为普通事实召回。
- 已确认（Q3=A）：PostgreSQL schema 使用保留既有业务数据的 forward migration，不沿用 destructive rebuild；迁移只演进本 change 所需 schema，并转换旧图耦合状态与 project jobs。
- 已确认（Q4=A）：图投影采用纯异步 durable job。事实权威事务成功即可返回并参与普通召回，请求内不执行 best-effort 同步全图重建。
- 已确认（Q5=A）：采用 coordinated single-version cutover，迁移期间不运行旧/新混合实例；回滚依赖迁移前备份或专门 forward recovery，不为滚动兼容恢复 `memory_edges`、双写或双轨。
- 已确认（Q6=A）：account 删除先立即封锁访问并清空/失活正文，保留最小不可访问 `deleting` owner/tombstone 与 cleanup job；Neo4j owner graph 清理成功后才物理删除 owner。
- 已确认（Q7=A）：保留现有命令入口和结果 code，`/memory status` 增加独立 graph pending/failed/reason，并修正自然语言“记住”及 `/memory show|update` 的事实 ready/graph pending 文案。
- 已确认：采用 AGI-saber 的能力边界而非仅复制名称，新增 `GraphMemory` application service；`graph.py` 保留 G1 值对象/规则，`maintenance.py` 保留 durable job consumer 职责。
- 已确认：Neo4j 与 PostgreSQL 一样由仓库根 Docker Compose 提供本地持久化容器；应用通过配置连接，Neo4j 故障仍按可选图能力降级。
- 已确认：完整 Shape 已获批准，以上 Outcome、Scope、约束、文件影响和 Verification expectations 作为 Build 基线。
- AGI-saber 依据：`GraphMemory` 在 LongTerm 之上增加 Neo4j 记忆节点/边，Neo4j 不可用时退化为 LongTerm；`KGStore` 负责文档 Entity 图，二者共享 Neo4j client 但使用不同 schema。VenAgent 采用这些行为边界，不复制其存储细节。

# Expected file impact

预计新增的生产结构：

```text
venagent/
  memory/
    graph_memory.py                 # GraphMemory application service
    maintenance.py                 # 独立 job consumer、退避与 shutdown
  infra/
    memory/
      neo4j/
        __init__.py                # M05 MemoryGraphStore 稳定导出
        graph.py                   # G1 节点壳、边、revision CAS、1-hop 与清理
    platform/
      neo4j/
        __init__.py                # 平台 Neo4j runtime/schema 稳定导出
        runtime.py                 # driver、session、连接池、deadline 与生命周期
        migrations.py              # 显式、幂等、版本化 constraint/index migration
```

预计新增的测试结构：

```text
tests/
  test_memory_maintenance.py       # lease/claim fencing、退避、恢复、shutdown
  test_memory_graph_store.py       # fake/Neo4j contract、revision、1-hop、隔离
  test_neo4j_integration.py        # 真实 Neo4j schema、事务、故障与清理（环境门控）
```

预计修改的主要文件：

- 根配置与运维：`pyproject.toml`、`.env.example`、`compose.yaml`、`README.md`，加入 Neo4j driver、官方固定版本容器、独立持久卷/健康检查、严格配置、显式 graph migration 与 single-version cutover 说明。
- composition/lifecycle：`venagent/bootstrap.py`、`venagent/interfaces/http/app.py`、`venagent/agent/runtime.py`、`venagent/observability.py`；装配/关闭共享 driver，启动独立 memory maintenance，并从 AgentRun worker 移除 memory job 消费。
- M05 application：`memory/ports.py`、`long_term.py`、`graph.py`、`service.py`、`write_pipeline.py`、`recall_provider.py`、`authorization.py`、`management.py`、`commands.py`、`health.py` 及必要稳定导出；拆分权威/图 port，加入 revision/claim 值，改为纯异步投影并修正状态文本。
- PostgreSQL memory adapter：`infra/memory/postgresql/__init__.py`、`long_term.py`、`jobs.py`、`row_mapping.py`；所有图影响 mutation 原子递增 revision/插入 job，增加 claim fence、自动恢复和有界 TTL 批处理。
- temporary test double：`infra/memory/temporary/__init__.py`、`state.py`、`long_term.py`、`graph.py`、`jobs.py`、`row_mapping.py`；保持非生产 graph contract 与测试隔离，不作为 durable fallback。
- 平台与删除：`infra/config/loader.py`、`infra/platform/__init__.py`、`runtime.py`、`migrations.py`、`errors.py`、`infra/platform/postgresql/ownership.py`、`ownership/service.py`；增加配置、资源状态、forward migration、deleting tombstone 与 cleanup-only claim 支持。
- 既有回归测试：`tests/conftest.py`、`test_memory_context.py`、`test_persistence.py`、`test_migration.py`、`test_config.py`、`test_test_configuration.py`、`test_startup_reporting.py`、`test_api.py`、`test_package_layout.py`、`test_ownership.py` 按受影响契约更新；真实 Neo4j 测试只接受显式 `TEST_NEO4J_URI`/测试凭据并使用隔离 owner/label 清理。

预计删除：

- `venagent/infra/memory/postgresql/graph.py`，并从 `PostgresMemoryStore` 继承和 schema 校验中移除全部 graph 方法/`memory_edges` 依赖。

明确不创建或不修改：

- 不新增 `web/` 页面、HTTP route/schema、M08/RAG package、通用 graph domain 或第二种图数据库 adapter。
- 不修改 `final/`、AGI-saber、`evals/memory/graph_gold_v1.jsonl` 的冻结召回语义；gold fixture 只作为等价性验证输入。
- 不创建 PostgreSQL edge compatibility adapter、双写器、backfill edge copier、进程内 production graph fallback、跨库存储协调器或 Neo4j 插件依赖。

上述是目标职责结构而非机械文件数量承诺。若 Build 中某个新文件过小，可在不混合 runtime/schema、平台/M05 或 application/adapter 边界的前提下合并；不得把这些职责重新集中进 `platform/runtime.py`、`memory/write_pipeline.py` 或单个 Neo4j client 文件。

# Open questions

- 无。

# Verification expectations

- 单元测试覆盖独立 graph port、关系 allowlist、owner/tenant/registry/revision/generation fencing、单事务 replace、幂等 job、事实 ready 与 graph pending 解耦、禁用/删除/过期/撤销和错误净化。
- 崩溃/并发测试覆盖每一类图影响 mutation 与 revision/job 原子提交、running job lease 恢复、过期 claim token 不能 complete/retry、重复 job、N/N+1 乱序投影、旧 worker fencing、请求末 authority revision 复核和 timeout 后连接池不泄漏。
- maintenance 测试覆盖无待执行 run 时仍能消费 projection/purge job、多进程/多 loop 竞争只提交最新 revision、超过旧 30 秒 lease 的长投影、Neo4j 连续失败后自动恢复、有界退避且不忙循环、异常可观察以及 lifespan shutdown 不遗留工作线程或连接。
- adapter contract 测试使用 non-durable fake 与 Neo4j adapter 的冻结 fixture；验证严格 1-hop、稳定排序、graph-only 上限和所有既有安全反例不回归。
- 集成测试在真实 PostgreSQL + Neo4j 环境中验证写入、失败降级、恢复重放、重启、并发 revision 漂移、owner purge 与无 `memory_edges` 依赖；环境不可用时必须如实记录未运行。
- 配置与 composition-root 测试覆盖 Neo4j 未配置、配置错误、启动不可达、运行期断连和资源关闭，不回显 URI、用户名或密码。
- Docker Compose smoke 验证固定 Neo4j 镜像、独立持久卷、健康检查、可配置端口、重启后数据仍在以及 PostgreSQL/Neo4j 状态互不误判；测试环境不得复用生产 volume，`docker compose down -v` 等破坏性清理只在明确的本地测试说明中出现。
- graph schema 测试覆盖显式 migration 的幂等性、缺失/旧/较新 schema 拒绝或降级、M05/M08 命名空间隔离以及应用启动不执行 DDL；不得用共享生产图上的全局 `MATCH (n) DETACH DELETE n` 做测试清理。
- 状态测试覆盖独立 graph pending/failed/reason 与修正后的现有命令文本，并证明 Neo4j graph pending 不再把已经持久化成功的事实标成 index pending 或阻止普通长期事实召回。
- migration 测试必须验证 forward migration 的数据保留语义；部署测试或运维说明必须验证 coordinated single-version cutover 与备份/forward recovery 回滚边界。account 删除测试必须在 Neo4j 断连、恢复、重复清理和进程重启后证明不存在孤立 owner graph。
- forward migration 测试覆盖旧 active fact 的 ready/pending/failed 状态、旧 pending/running/failed project job、无 facts owner、多个 tenant、重复执行和中途失败恢复；证明迁移后普通事实立即按权威资格可见，旧 worker/job 不会写新图，每个需重建的 owner/tenant 最终只有最新 revision 生效。
- 冷重建至少记录 100/500/1000 活动事实下的边生成耗时、边数量、Neo4j transaction 参数体积和 provider/query timeout 结果；该证据用于暴露 O(n^2) 剩余风险，不得为通过测试截断应生成的边。
- 运行相关 pytest、完整 pytest、Ruff、compileall、Comet check，并人工复核 M05/M08 边界、无双写/回退、无跨存储伪原子和 dirty worktree 保护；未运行项不得写成通过。
