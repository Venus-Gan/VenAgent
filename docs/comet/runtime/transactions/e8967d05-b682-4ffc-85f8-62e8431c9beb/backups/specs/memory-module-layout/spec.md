# memory-module-layout 完整目标规格

## 1. 目标

VenAgent SHALL 在不改变 M05 G1 1-hop 候选、评分、安全和用户命令行为的前提下，以职责清晰、可测试且符合 ECC 文件规模约束的模块承载 memory 业务用例、存储 port 和 adapter。M05 SHALL 把权威长期记忆与图投影拆成独立 port：PostgreSQL 继续承载 settings/facts/sources/lifecycle/jobs，Neo4j 成为唯一 durable edge store。公开业务入口保持稳定；内部 runtime 类型、数据库 schema、事务与异常边界按该存储契约显式演进。

本 change 同时 SHALL 修复当前整体包边界：不得因为 M05 引入而让 conversation、agent、ownership、memory 互相借用错误定义、聚合 store 或重复上下文模型。

## 1.1 整体所有权矩阵

| 包 | 权威事实/行为 | 允许依赖 | 明确不拥有 |
|---|---|---|---|
| `conversation/` | Conversation、ConversationMessage、对话标题、对话用例 | ownership 身份值、agent run 的显式 port/读模型 | memory 事实、最终 prompt 投影、数据库细节 |
| `agent/` | AgentRun 状态机、worker lifecycle、LangGraph state、ContextProjection | conversation 消息读模型、memory recall provider | 对话 CRUD、长期事实写入、HTTP 错误映射 |
| `ownership/` | owner/user/session、身份和授权决策 | 自身 port | conversation/memory/agent 业务规则 |
| `memory/` | short/long/G1、来源资格、记忆管理、召回候选 | conversation 消息只读输入、ownership 授权快照 | ConversationMessage 权威、最终预算投影、adapter 事务 |
| `interfaces/` | HTTP/命令输入输出和错误映射 | feature service 与稳定 port | 业务事实和存储实现 |
| `infra/` | port adapter、迁移、连接池、运行模式、checkpointer | 所有 feature port/model 的映射 | feature use case、HTTP/命令解析 |

依赖方向 SHALL 保持为 `interfaces -> feature services/ports <- infra adapters`；具体 adapter 只由 `bootstrap.py` 装配，feature service 不得导入具体 adapter。

## 2. 模块所有权

- `venagent/memory/` SHALL 保留为 M05 能力中心，按 `short_term.py`、`long_term.py`、`graph.py`、`recall_provider.py`、`write_pipeline.py`、`management.py`、`authorization.py`、`policy.py`、`ports.py`、`errors.py` 和 `health.py` 形成职责边界；不得采用全项目 layer-first 或 `personal_memory` 目录作为本 change 的目标。
- `venagent/infra/memory/` SHALL 只实现 M05 已冻结 port 的 adapter；不得把业务规则、context 最终投影或平台 owner/conversation/run 状态放入其中。
- `venagent/infra/platform/` SHALL 负责 PostgreSQL/Neo4j/temporary 资源生命周期、显式 schema migration、官方 checkpointer 装配与启动模式选择；不得拥有 conversation、agent、ownership 或 M05 业务用例。未来 M08 可以共享平台级 Neo4j driver/runtime，但不得共享 M05 graph adapter、label、schema 或查询。
- `venagent/infra/platform/memory.py` 与聚合式 `venagent/infra/platform/postgres.py` SHALL 被移除；平台 adapter SHALL 按 `temporary/` 与 `postgresql/` 后端拆分 state、ownership 和 conversation runtime 职责。
- `automatic_title` SHALL 从平台 adapter 迁移到 `venagent/conversation/title.py`，因为标题生成属于 conversation 业务规则，不属于持久化 adapter。
- `final/` SHALL 继续作为 legacy/reference 范围，不属于本 change 的活动实现或验收对象。

## 2.1 错误所有权与 port 边界

- `conversation/errors.py` SHALL 只承载对话输入、生命周期、标题和幂等错误，例如 `ConversationNotFound`、`ConversationBusy`、`InvalidMessage`；它不再承载 adapter 错误。
- `memory/errors.py` SHALL 只承载记忆授权、开关、策略、游标、确认、删除 generation、事实生命周期和稳定的图能力错误，例如 `MemoryUnauthorized`、`MemoryDisabled`、`MemoryNotFound`；`ConversationNotFound` 不得迁入 memory，Neo4j 驱动异常或连接细节不得穿透 port。
- `ownership/errors.py` SHALL 只承载 token、session、account 和 identity 错误。
- `agent/errors.py` SHALL 作为 agent 错误归属点，承载现有 `RunError`/run 状态错误和 `ContextProjectionError`/预算错误；`agent/runs.py` 与 `agent/context.py` 可保留行为实现，但从该模块导入错误。
- `memory/commands.py` SHALL 自己定义确定性命令解析错误（例如 `InvalidMemoryCommand`），不得把命令语法错误伪装成记忆事实错误。
- `conversation/ports.py`、`memory/ports.py`、`ownership/ports.py` 和 `agent/ports.py` SHALL 分别定义本 feature 的安全 adapter 错误；不得继续让 memory、ownership、agent 或平台迁移借用 `conversation.ports.StoreError`。
- `infra/platform/errors.py` SHALL 只承载迁移、连接池、schema compatibility 等平台级错误；它不得成为 feature service 的通用错误基类。
- 不得创建根级 catch-all `errors.py`，也不得以共享基类掩盖不同聚合的错误码、重试语义或安全边界。

## 3. 稳定公开表面

- `venagent.memory` SHALL 保持为 M05 能力的公开 package；现有稳定入口在不改变用户行为的前提下继续导出，`MemoryService` 如保留 SHALL 只作为薄 façade，不得继续集中全部用例。
- 平台 adapter 的仓库内调用方 SHALL 迁移到新的包级导出；旧内部 import path 不作为长期兼容表面，不得为保留错误的 `memory` 命名留下永久 shim。
- 平台类型 SHALL 使用 `TemporaryPlatformState`、`TemporaryOwnershipStore`、`TemporaryConversationRuntimeStore`、`PostgresOwnershipStore` 和 `PostgresConversationRuntimeStore` 等能同时表达后端与职责的名称。
- 平台内部类型可迁移，但不得使 interfaces、bootstrap 或业务调用方依赖 adapter 私有实现。
- `conversation.ports` SHALL 只定义 ConversationStore 与 conversation-facing 操作；`agent.ports`/`agent.runs` SHALL 定义 RunStore 与 worker lifecycle 操作。不得通过 `RuntimeStore(RunStore, Protocol)` 重新把两个 feature 聚合到 conversation port。
- `infra/platform/runtime.py` SHALL 组合 feature adapter ports，负责启动模式选择、Neo4j 可选资源生命周期和 wiring；它不向上暴露具体 `Temporary*Store`、`Postgres*Store` 或 Neo4j driver 类型。
- Neo4j graph schema SHALL 通过显式、幂等且有版本校验的 migration/bootstrap 入口管理；application runtime 只连接并验证兼容性，不在正常启动时创建约束/索引或吞掉 DDL 错误。PostgreSQL 与 Neo4j migration 分别提交、分别报告，不能伪装成跨库原子迁移。

## 4. 职责拆分

- `short_term.py` SHALL 负责完整 turn 选择、窗口预算、摘要生成/校验/降级；其消息权威必须是 `ConversationMessage`，不得维护第二份消息事实。
- `long_term.py` SHALL 负责 `MemoryFact`、`MemorySource`、资格后的生命周期、TTL、冲突/quarantine/superseded、来源撤销和删除语义；不得直接依赖 psycopg、embedding SDK 或具体向量数据库。
- `graph.py` SHALL 负责 G1 关系规则、边构建、重放、authority/applied revision、generation 值对象和注册表校验；不得直接连接 Neo4j 或持有数据库事务。
- `graph_memory.py` SHALL 承载 `GraphMemory` application service，消费 PostgreSQL 权威 `MemoryStore` 与独立 `MemoryGraphStore`，协调权威 snapshot、完整投影、1-hop graph snapshot、revision fencing 和清理；它不得拥有 driver/session、job claim loop、HTTP 或最终 ContextProjection。
- `memory/recall_provider.py` SHALL 组合已经完成授权和生命周期校验的短期/长期/G1 provider，输出 `ContextBlock`；最终 section/global budget 和 model placement 仍由 `agent/context.py` 完成。M05 不得再创建 `memory/context.py`，避免与 agent 的最终上下文职责重名。
- `write_pipeline.py` SHALL 编排用户消息/明确授权工具结果的候选提取、策略过滤、来源绑定和异步提交；assistant 自由文本、摘要和最终 prompt 不得获得长期来源资格。
- `management.py` SHALL 承载 list/show/status/update/forget/revoke/delete 等 application use case；`commands.py` 只负责确定性解析和结果映射。
- `write_pipeline.py` 或独立内聚模块 SHALL 承载 memory job dispatch；应用 lifespan SHALL 启停独立 memory maintenance consumer，`AgentRuntime` 不再顺带领取 projection/purge/owner-cleanup job。job adapter 负责 claim/lease token 与 fenced terminal transition，图 adapter 不拥有队列调度。
- `maintenance.py` SHALL 只负责 durable job 的领取、lease/claim fence、dispatch、退避、状态转移和 shutdown；graph job 委托 `GraphMemory`，不得把构边、Neo4j 查询、评分或事实生命周期规则复制进 worker。
- `authorization.py`、`policy.py` 和 `ports.py` SHALL 作为清晰边界，不把授权、敏感信息或 adapter 细节重新塞回 `long_term.py`。`MemoryStore` 与 `MemoryGraphStore` SHALL 是独立消费方 port；业务用例不得通过具体 PostgreSQL 或 Neo4j adapter 协调跨库行为。
- 平台 temporary 与 PostgreSQL adapter SHALL 分别实现相同的 `OwnershipStore`、`ConversationStore` 与 `RunStore` 消费方 port；拆分不得改变 owner/session、conversation/message、run/claim、事务、fencing、删除和恢复行为。

M05 feature-first 目标布局（文件可以在实现时按实际依赖合并，但不得回到单一模糊模块）：

```text
venagent/
  ownership/
    errors.py                # owner/user/session/identity 错误
    models.py                # Actor、Owner、User、Session 权威模型
    ports.py                 # OwnershipStore、凭据/token port 与 OwnershipStoreError
    service.py               # 身份与账号 use case
  conversation/
    errors.py                # 对话输入、生命周期、标题与幂等错误
    models.py                # Conversation 与 ConversationMessage
    ports.py                 # ConversationStore 与 ConversationStoreError；不继承 RunStore
    service.py               # 对话 use case；显式消费 RunStore
    title.py                 # automatic_title 业务规则
  agent/
    errors.py                # run 状态与 ContextProjection 错误
    runs.py                  # AgentRun 模型、状态机与生命周期
    ports.py                 # RunStore、RunStoreError、模型调用与运行时 port
    state.py                 # LangGraph state
    context.py               # 唯一的最终上下文预算与投影
    runtime.py               # worker、恢复、执行编排
  memory/
    __init__.py              # M05 稳定导出
    short_term.py            # ConversationMessage 驱动的短期窗口与摘要
    long_term.py             # 长期事实、来源与生命周期
    graph.py                 # G1 关系规则与重放
    graph_memory.py          # GraphMemory application service 与跨 port 协调
    recall_provider.py       # 记忆 ContextBlock provider
    write_pipeline.py        # 候选提取与长期写入流水线
    maintenance.py           # 独立 memory job consumer、退避与 shutdown
    management.py            # 管理 use case
    authorization.py         # MemoryAuthorization
    policy.py                # 来源/敏感/稳定性策略
    ports.py                 # MemoryStore/MemoryGraphStore ports 与稳定错误
    errors.py                # 稳定错误分类
    health.py                # M05 capability health
  infra/
    memory/
      temporary/
        __init__.py
        state.py             # temporary memory adapter 的共享容器与锁
        long_term.py         # 长期事实、来源、设置与删除 adapter
        short_term.py        # 摘要 adapter
        graph.py             # non-durable G1 graph test double
        jobs.py              # 后台 job adapter
      postgresql/
        __init__.py
        long_term.py         # PostgreSQL 长期事实、来源与生命周期 adapter
        short_term.py        # PostgreSQL 摘要 adapter
        jobs.py              # PostgreSQL 后台 job adapter
        row_mapping.py       # memory 行到领域模型的映射
      neo4j/
        __init__.py          # M05 graph adapter 稳定导出
        graph.py             # Neo4j G1 节点壳、边、revision 与清理 adapter
    platform/
      __init__.py            # 平台 runtime、migration 与 adapter 导出
      runtime.py             # 后端选择、checkpointer、PG/Neo4j 资源与健康状态
      migrations.py          # 显式 PostgreSQL schema migration
      errors.py              # 平台迁移、连接池与 schema 错误
      neo4j/
        __init__.py          # 平台 Neo4j runtime 与 migration 稳定导出
        runtime.py           # driver、连接池、deadline 与资源生命周期
        migrations.py        # 显式 Neo4j constraint/index migration 与版本校验
      temporary/
        __init__.py
        state.py             # TemporaryPlatformState 与 request 记录
        ownership.py         # TemporaryOwnershipStore
        conversation_runtime.py  # TemporaryConversationRuntimeStore
      postgresql/
        __init__.py
        ownership.py         # PostgresOwnershipStore
        conversation_runtime.py  # PostgresConversationRuntimeStore
        row_mapping.py       # PostgreSQL 行到领域模型的映射
  interfaces/
    http/
      errors.py              # feature/port 错误到稳定 HTTP 响应的映射
```

实现可在不破坏内聚性和 800 行硬上限的前提下合并过小文件，但不得重新创建 `platform/memory.py` 或聚合式 `platform/postgres.py`，也不得以 `models.py` 汇总所有 M05 定义而不保留行为边界。`memory/recall_provider.py` 是 provider，不是最终上下文投影；最终投影唯一位于 `agent/context.py`。

## 5. 命名与规模约束

- 活动 adapter 实现文件名 SHALL 表达后端与职责；平台非持久降级 adapter 使用已有模式名 `temporary`，不得使用易与 M05 混淆的 `memory` 或含义不充分的 `in_memory`。
- 本 change 重构触及的生产 `.py` 文件 SHALL 不超过 800 行；常规模块 SHOULD 保持约 200-400 行。超过常规范围时必须由内聚职责或事务完整性解释，不能用重复、转发样板或无意义拆分满足行数。
- 不得引入循环 import。package `__init__.py` 只提供稳定导出，不承载业务逻辑或产生隐式初始化副作用。Neo4j driver 由平台 runtime 创建和关闭，M05 adapter 不私自创建第二个全局 client。
- `final/internal/platform/neo4j.py` 与 `final/internal/memory/graph_memory.py` 不属于当前 `venagent/` composition root，且缺少 owner/tenant、revision、事务和秘密边界；Build 不得从 `final/` 导入或复制其 client、全局 label、启动 DDL、daemon thread 或错误转空集合实现。
- 公共函数和协议方法 SHALL 保持明确类型标注；资源和事务 SHALL 使用既有上下文管理方式并显式处理失败。
- 实现 SHALL 在授权/fencing、来源资格、事务提交与回答发布顺序、删除 generation、provider 降级、图关系重放等非显然处添加简洁的“为什么”注释；不得为显然赋值或逐行转述代码添加噪声注释。

## 6. 行为与演进约束

- 本 change SHALL NOT 修改 M05 的命令入口、结果 code、HTTP schema、授权/owner/tenant 隔离、敏感信息策略、来源资格、事实生命周期、图关系生成、1-hop 召回门控或排序语义。现有 status/remember/show/update 文本和计数 SHALL 按已确认的事实 ready/graph ready 语义修正并增加独立 graph pending/failed/reason，不新增命令或前端表面。
- PostgreSQL schema SHALL 移除 `memory_edges` 及其必需校验，并增加持有 owner/tenant 单调 `authority_revision` 和 durable projection job fencing 所需的最小权威字段或表；每个图影响 mutation 必须与 revision 递增和 job 插入同事务提交。不得把边内容换名保留在 PostgreSQL。现有 edge rows 不迁移、不双写，Neo4j 图只从 PostgreSQL 权威 facts/sources 冷重建。
- forward migration SHALL 保留 owners、conversations、runs、checkpoints、memory facts/sources/jobs 等既有业务数据，owner/tenant projection authority SHALL 使用明确复合身份；迁移 SHALL 归一化旧图耦合 `index_status`、取消或转换缺少 target revision/claim fence 的旧 project job，并为每个需要重建的 owner/tenant 幂等建立初始 revision/job。不得让旧 pending/failed 图状态继续阻止合格事实普通召回，也不得丢弃非图业务数据或把 Neo4j 网络调用放进 PostgreSQL migration transaction。
- 本 change 可以新增 Neo4j driver 依赖、严格环境配置、平台资源生命周期和 M05 graph provider；不得新增前端表面、M08 provider、其他图数据库或与 G1 存储无关的产品配置。
- 根 `compose.yaml` SHALL 增加与 PostgreSQL 并列的 Neo4j 服务，使用固定受支持官方镜像、独立持久 volume、可配置 Bolt/HTTP 宿主端口、健康检查和 restart policy；不得使用 `latest`、仓库内真实/通用默认秘密或非必要 Neo4j 插件。容器健康不替代应用 schema compatibility 检查，Neo4j 故障不改变 PostgreSQL durable mode。
- 若拆分过程中发现与 Neo4j 唯一边存储、跨库 fencing 或事实/图 readiness 解耦无关的行为缺陷，SHALL 记录为独立后续 change，不得顺带修复。
- AGI-saber 仅作为短期/长期记忆、写入管线、recall source、context assembler、GraphMemory/KGStore 分界和 Neo4j 不可用时退化到 LongTerm 的职责事实来源；不得迁移其 Go 包结构、表结构、goroutine 写入方式、节点正文复制、assistant 派生事实策略或具体长期聚合实现。

## 7. 验收

- 稳定公开导入和应用 composition root 在重构后可用；`MemoryService` 只消费独立的权威 memory port 与 graph port，Neo4j 未配置/不可用时按契约禁用或降级 G1 而不阻塞普通事实召回。
- 活动实现中不存在 `venagent/infra/platform/memory.py` 或聚合式 `venagent/infra/platform/postgres.py`；M05 adapter 的旧文件去留以重新确认后的完整目标布局为准；本 change 触及的生产文件满足 800 行硬上限。
- 针对 capability protocol、façade 委托、adapter 一致性、权威 mutation/revision/job 原子提交、Neo4j 单事务 replace、authority/applied revision fencing、乱序 worker、事务/异常传播和无循环依赖的测试可重复通过。
- PostgreSQL migration、schema 校验和活动 adapter 不再创建、要求、读取或写入 `memory_edges`；不存在 durable edge fallback、shadow copy 或双写。Neo4j 节点不包含事实/来源正文，冷重建只从 PostgreSQL 权威 facts/sources 生成。
- memory 相关测试、完整项目 pytest、PostgreSQL 集成测试、Ruff（若可用）、`compileall` 和 Comet 检查均记录实际结果；完整测试结果不得低于 M05 Verify 的 154 个通过基线。
- 人工复核确认 feature service 不依赖具体 adapter、infra 不承载 feature use case，且 legacy `final/` 未被修改。
- 人工复核确认 conversation、memory、ownership、agent 的领域错误与各自 port 错误边界互不混用；`conversation.ports` 不再成为跨 feature 的基础设施异常来源。
- 人工复核确认 M05 记忆规则集中在 short/long/graph/recall provider 等职责文件中，关键设计原因注释存在且准确，未重新形成 god service 或 catch-all models 文件。

## 8. 与 memory-context 的关系

- 本规格只约束 M05 活动代码的内部模块布局与兼容性，不替代 `memory-context` 的产品、授权、安全、数据、图和评测契约。
- 两份规格冲突时，用户可见行为、安全和数据语义以 `memory-context` 为准；本规格以行为保持方式约束其实现结构。
