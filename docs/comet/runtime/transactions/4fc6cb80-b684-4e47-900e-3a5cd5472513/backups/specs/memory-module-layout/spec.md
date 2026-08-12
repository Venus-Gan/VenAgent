# memory-module-layout 完整目标规格

## 1. 目标

VenAgent SHALL 在不改变 M05 G1 1-hop 候选、评分、安全和用户命令行为的前提下，以职责清晰、可测试且符合 ECC 文件规模约束的模块承载 memory 业务用例、存储 port 和 adapter。M05 SHALL 把权威长期记忆与图投影拆成独立 port：PostgreSQL 继续承载 settings/facts/sources/lifecycle/jobs，Neo4j 成为唯一 durable edge store。公开业务入口保持稳定；内部 runtime 类型、数据库 schema、事务与异常边界按该存储契约显式演进。

本 change 同时 SHALL 修复当前整体包边界：不得因为 M05 引入而让 conversation、agent、ownership、memory 互相借用错误定义、聚合 store 或重复上下文模型。

## 1.1 整体所有权矩阵

| 包 | 权威事实/行为 | 允许依赖 | 明确不拥有 |
|---|---|---|---|
| `conversation/` | Conversation、ConversationMessage、对话标题、对话用例 | ownership 身份值、agent run 的显式 port/读模型 | memory 事实、最终 prompt 投影、数据库细节 |
| `agent/` | AgentRun 状态机、worker lifecycle、LangGraph state | conversation 消息读模型、promptctx 装配入口、memory runtime port | 对话 CRUD、长期事实写入、通用 ContextProjection、HTTP 错误映射 |
| `ownership/` | owner/user/session、身份和授权决策 | 自身 port | conversation/memory/agent 业务规则 |
| `memory/` | short/long/G1、来源资格、记忆管理、召回候选 | conversation 消息只读输入、ownership 授权快照 | ConversationMessage 权威、最终预算投影、adapter 事务 |
| `promptctx/` | ContextBlock、schema/policy、source contract、确定性投影与预算 | 已过滤的类型化 source 输出 | memory 生命周期、agent State、数据库 I/O |
| `interfaces/` | HTTP/命令输入输出和错误映射 | feature service 与稳定 port | 业务事实和存储实现 |
| `repo/` | feature port adapter 与后端映射 | feature models/ports、注入的平台资源 | feature use case、连接资源、HTTP/命令解析 |
| `platform/` | 连接资源、迁移、checkpointer、启动状态、安全 adapter | 注入配置与技术 SDK | feature adapter、业务事实和 use case |

依赖方向 SHALL 保持为 `interfaces -> feature services/ports <- repo/platform/llm adapters`；具体 adapter 只由 `bootstrap.py` 装配，feature service 不得导入具体 adapter，platform 不得构造 repo adapter。

## 2. 模块所有权

- `venagent/memory/` SHALL 保留为 M05 能力中心，按 `short_term.py`、`long_term/`、`graph.py`、`graph_memory.py`、`recall.py`、`jobs.py`、`job_worker.py`、`management.py`、`authorization.py`、`capabilities.py`、`ports.py`、`errors.py` 和薄 `service.py` 形成职责边界。
- `venagent/promptctx/` SHALL 成为通用上下文唯一所有者；memory 只拥有候选召回与排序，不直接依赖 agent 或拼装最终模型输入。
- `venagent/repo/*/memory/` 与 `venagent/repo/neo4j/memory_graph.py` SHALL 只实现 M05 已冻结 port 的 adapters；不得把业务规则、最终投影或平台资源生命周期放入其中。
- `venagent/platform/` SHALL 负责 PostgreSQL/Neo4j 资源生命周期、显式 schema migration、官方 checkpointer、启动模式与安全技术能力；不得拥有或构造 conversation、agent、ownership 或 M05 adapters。
- 活动实现 SHALL 移除整个 `venagent/infra/`，不得为旧内部路径保留永久 shim。
- 标题与输入约束 SHALL 合并到 `venagent/conversation/rules.py`，因为二者都是 conversation 规则。
- `final/` SHALL 继续作为 legacy/reference 范围，不属于本 change 的活动实现或验收对象。

## 2.1 错误所有权与 port 边界

- `conversation/errors.py` SHALL 只承载对话输入、生命周期、标题和幂等错误，例如 `ConversationNotFound`、`ConversationBusy`、`InvalidMessage`；它不再承载 adapter 错误。
- `memory/errors.py` SHALL 只承载记忆授权、开关、策略、游标、确认、删除 generation、事实生命周期和稳定的图能力错误，例如 `MemoryUnauthorized`、`MemoryDisabled`、`MemoryNotFound`；`ConversationNotFound` 不得迁入 memory，Neo4j 驱动异常或连接细节不得穿透 port。
- `ownership/errors.py` SHALL 只承载 token、session、account 和 identity 错误。
- `agent/errors.py` SHALL 只承载 agent run/graph 错误；通用 ContextProjection/预算错误归 `promptctx/errors.py`。
- `memory/command_adapter.py` SHALL 自己定义确定性命令解析错误（例如 `InvalidMemoryCommand`）和命令结果模型，不得把命令语法错误伪装成记忆事实错误。
- `conversation/ports.py`、`memory/ports.py`、`ownership/ports.py` 和 `agent/ports.py` SHALL 分别定义本 feature 的安全 adapter 错误；不得继续让 memory、ownership、agent 或平台迁移借用 `conversation.ports.StoreError`。
- `platform/errors.py` SHALL 只承载迁移、连接池、schema compatibility 等平台级错误；它不得成为 feature service 的通用错误基类。
- 不得创建根级 catch-all `errors.py`，也不得以共享基类掩盖不同聚合的错误码、重试语义或安全边界。

## 3. 稳定公开表面

- `venagent.memory` SHALL 保持为 M05 能力的公开 package；`MemoryService` SHALL 保留稳定公开 façade，但通过显式组合委托给 `MemoryAuthorizer`、`MemoryManager`、`LongTermWriter`、`MemoryRecall` 与 `MemoryJobs`，不得使用依赖 MRO 和共享私有宿主字段的 mixin 多继承。
- 平台 adapter 的仓库内调用方 SHALL 迁移到新的包级导出；旧内部 import path 不作为长期兼容表面，不得为保留错误的 `memory` 命名留下永久 shim。
- repo adapter 类型 SHALL 使用 `TemporaryPlatformState`、`TemporaryOwnershipStore`、`TemporaryConversationRuntimeStore`、`PostgresOwnershipStore` 和 `PostgresConversationRuntimeStore` 等能同时表达后端与职责的名称。
- 平台内部类型可迁移，但不得使 interfaces、bootstrap 或业务调用方依赖 adapter 私有实现。
- `conversation.ports` SHALL 只定义 ConversationStore 与 conversation-facing 操作；`agent.ports`/`agent.runs` SHALL 定义 RunStore 与 worker lifecycle 操作。不得通过 `RuntimeStore(RunStore, Protocol)` 重新把两个 feature 聚合到 conversation port。
- `platform/runtime.py` SHALL 只组合 backend-neutral resources/status/lifecycle；`platform/postgresql/runtime.py` 拥有 pools、schema validation 与 checkpointer 生命周期。feature adapter wiring 只在 `bootstrap.py` 完成。
- Neo4j graph schema SHALL 通过显式、幂等且有版本校验的 migration/bootstrap 入口管理；application runtime 只连接并验证兼容性，不在正常启动时创建约束/索引或吞掉 DDL 错误。PostgreSQL 与 Neo4j migration 分别提交、分别报告，不能伪装成跨库原子迁移。

## 4. 职责拆分

- `short_term.py` SHALL 负责完整 turn 选择、窗口预算、摘要生成/校验/降级；其消息权威必须是 `ConversationMessage`，不得维护第二份消息事实。
- `long_term/facts.py` SHALL 负责 `MemoryFact`、`MemorySource` 与分页读模型；`long_term/policy.py` 负责候选提取、资格、安全和有效期规则；`long_term/writer.py` 负责写入、版本化、冲突/quarantine 处理。三者不得直接依赖 psycopg、embedding SDK 或具体向量数据库。
- `graph.py` SHALL 负责 G1 关系规则、边构建、重放、authority/applied revision、generation 值对象和注册表校验；不得直接连接 Neo4j 或持有数据库事务。
- `graph_memory.py` SHALL 承载 `GraphMemory` application service，消费 PostgreSQL 权威 `MemoryStore` 与独立 `MemoryGraphStore`，协调权威 snapshot、完整投影、1-hop graph snapshot、revision fencing 和清理；它不得拥有 driver/session、job claim loop、HTTP 或最终 ContextProjection。
- `memory/recall.py` SHALL 组合授权、生命周期、短期/长期/G1 候选与排序；`promptctx/recall_provider.py` 只把已合格候选转换为 `ContextBlock`，最终 section/global budget 和 model placement 由 `promptctx/assembler.py` 完成。
- `long_term/writer.py` SHALL 编排用户消息/明确授权工具结果的候选提取、策略过滤、来源绑定和同步事实写入；assistant 自由文本、摘要和最终 prompt 不得获得长期来源资格。
- `management.py` SHALL 承载 list/show/status/update/forget/revoke/delete 等 application use case；`command_adapter.py` 只负责确定性解析和结果映射。
- `jobs.py` SHALL 承载 job 值对象、claim/dispatch/retry/fencing 行为；`job_worker.py` 只负责 lifespan polling 与 shutdown，graph job 委托 `GraphMemory`。
- `authorization.py`、`long_term/policy.py` 和 `ports.py` SHALL 作为清晰边界；`MemoryStore` SHALL 在同一文件中拆为 fact/summary/job 等窄消费方 Protocol，完整 adapter 可实现组合 Protocol，`MemoryGraphStore` 保持独立。
- repo temporary 与 PostgreSQL adapters SHALL 分别实现相同的 `OwnershipStore`、`ConversationStore` 与 `RunStore` 消费方 port；拆分不得改变事务、fencing、删除和恢复行为。

M05 feature-first 目标布局（文件可以在实现时按实际依赖合并，但不得回到单一模糊模块）：

```text
venagent/
  memory/
    authorization.py
    capabilities.py
    command_adapter.py
    errors.py
    graph.py
    graph_memory.py
    jobs.py
    job_worker.py
    management.py
    ports.py
    recall.py
    service.py
    short_term.py
    long_term/
      facts.py
      policy.py
      writer.py
  promptctx/
    assembler.py
    context.py
    errors.py
    recall_provider.py
    schema.py
    source.py
  repo/
    postgresql/
      conversation.py
      conversation_mapping.py
      conversation_runtime.py
      ownership.py
      runs.py
      memory/
        jobs.py
        long_term.py
        row_mapping.py
        short_term.py
    temporary/
      conversation.py
      conversation_runtime.py
      ownership.py
      runs.py
      state.py
      memory/
        fact_state.py
        graph.py
        jobs.py
        long_term.py
        short_term.py
        state.py
    neo4j/
      memory_graph.py
  platform/
    errors.py
    observability.py
    runtime.py
    postgresql/
      migrations.py
      runtime.py
    neo4j/
      migrations.py
      runtime.py
    security/
      passwords.py
      tokens.py
```

实现 SHALL 遵守该已批准文件归属，不得为目录对称预建 short-term 子包或 M06--M09 文件。`memory/recall.py` 不是最终上下文投影；最终通用投影唯一位于 `promptctx/`。

## 5. 命名与规模约束

- 活动 adapter 实现文件名 SHALL 表达后端与职责；非持久 adapter 使用模式名 `temporary`。PostgreSQL ownership 映射归 `ownership.py`，conversation/message/run 共享映射归 `conversation_mapping.py`，temporary memory 的 tombstone/hash helper 归 `fact_state.py`；不得用不存在 row 的 `row_mapping.py` 掩盖职责。
- 本 change 重构触及的生产 `.py` 文件 SHALL 不超过 800 行；常规模块 SHOULD 保持约 200-400 行。超过常规范围时必须由内聚职责或事务完整性解释，不能用重复、转发样板或无意义拆分满足行数。
- 不得引入循环 import。package `__init__.py` 只提供稳定导出，不承载业务逻辑或产生隐式初始化副作用。Neo4j driver 由 `platform/neo4j/runtime.py` 创建和关闭，M05 adapter 不私自创建第二个全局 client。
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
- 活动实现中不存在整个 `venagent/infra/`；M05 adapter、platform resources 和 promptctx 均位于批准目录，且本 change 触及的生产文件满足 800 行硬上限。
- 针对 capability protocol、façade 委托、adapter 一致性、权威 mutation/revision/job 原子提交、Neo4j 单事务 replace、authority/applied revision fencing、乱序 worker、事务/异常传播和无循环依赖的测试可重复通过。
- PostgreSQL migration、schema 校验和活动 adapter 不再创建、要求、读取或写入 `memory_edges`；不存在 durable edge fallback、shadow copy 或双写。Neo4j 节点不包含事实/来源正文，冷重建只从 PostgreSQL 权威 facts/sources 生成。
- memory 相关测试、完整项目 pytest、PostgreSQL 集成测试、Ruff（若可用）、`compileall` 和 Comet 检查均记录实际结果；完整测试结果不得低于 M05 Verify 的 154 个通过基线。
- 人工复核确认 feature service 不依赖具体 adapter、repo/platform 不承载 feature use case、bootstrap 是唯一 adapter 装配点，且 legacy `final/` 未被修改。
- 人工复核确认 conversation、memory、ownership、agent 的领域错误与各自 port 错误边界互不混用；`conversation.ports` 不再成为跨 feature 的基础设施异常来源。
- 人工复核确认 M05 记忆规则集中在 short/long-term/graph/recall/jobs 等职责文件中，MemoryService 使用显式组合，memory 不依赖 agent，未重新形成 god service 或 catch-all models 文件。

## 8. 与 memory-context 的关系

- 本规格只约束 M05 活动代码的内部模块布局与兼容性，不替代 `memory-context` 的产品、授权、安全、数据、图和评测契约。
- 两份规格冲突时，用户可见行为、安全和数据语义以 `memory-context` 为准；本规格以行为保持方式约束其实现结构。
