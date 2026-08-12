# Outcome

为 VenAgent 当前 M01--M05 活动实现建立一套与真实职责、调用关系和测试边界一致的 Python package 目录基调。该基调移除含义过宽的 `infra/` 根目录，明确 feature、repository adapter、平台资源、LLM、配置、HTTP transport 和 composition root 的所有权，并以模块内聚性决定文件合并或拆分，不机械复制旧 `final/` 或附件中的预计文件名。

# Scope

- 审核并规划 `venagent/` 当前 M01--M05 的 package、模块、公开导出、import、composition root、架构测试和 README 目录树迁移。
- 恢复独立 `promptctx/` package，承载模型调用上下文契约、schema/policy、纯装配与类型化 source 边界，并明确它与 agent orchestration、memory recall 的依赖方向。
- 为 `infra/` 中的现有 adapter 与技术能力确定新的明确归属；迁移不得改变业务行为、HTTP/SSE 契约、数据库 schema、配置来源或公开用户结果。
- 对照旧 `final/` 的职责组合方式，识别当前模块中名称与实际内容不一致、过度拆分、过度聚合和后端拆分不对称的文件。
- 只记录 M06--M09 的目录规划原则和参考落点；实际模块进入各自 Shape 后再根据真实消费者、端口和测试确定文件，不预建 package 或空实现。
- 更新所有受路径变化影响的 canonical specs，避免新目录与既有 `feature-first-boundaries`、`memory-module-layout`、`memory-context`、配置及 README 规格并存冲突。

# Non-goals

- 本 Shape 不实现目录迁移，不修改活动 Python、Vue、数据库或部署行为。
- 不实现或预建 M06 tools/sandbox、M07 planner/subagent、M08 document/RAG 或 M09 queue/operator 文件。
- 不恢复 `final/` 的巨型 `memory.py`、全局 service、直接数据库 client 或其他 legacy 架构。
- 不照搬 `final/promptctx` 中尚无当前消费者的 profile/planner/taskmem/tools/RAG source、万能 SlotFilter 或 source registry；M06--M08 只在真实模块进入时增加自己的 source。
- 不在用户完成文件合并讨论和最终共享理解确认前调用 `next` 或进入 Build。

# Acceptance examples

- 给定迁移后的活动包，`venagent/infra/` 不存在；当前 M01--M05 的每个具体 adapter、连接资源、配置和 provider 均能在新路径找到唯一所有者，且 `bootstrap.py` 仍是唯一装配点。
- 给定任一 feature 模块，文件名描述其真实职责；例如只保存事实与来源值对象的模块不会宣称自己实现完整长期记忆生命周期。
- 给定任一模型调用，`promptctx/` 是 ContextBlock、投影 policy、预算报告和最终 ModelCallContext 的唯一通用所有者；agent 负责运行节点编排，memory 负责授权、生命周期、召回与排序事实。
- 给定 temporary 与 PostgreSQL 两套 adapter，相同 feature port 的职责拆分可对照；后端差异保留在实现内，不把业务规则复制成两套不同语义。
- 给定 M06--M09 尚未开始，活动树中不存在对应空目录；规划文档仍能说明未来 change 应从哪些现有边界扩展。
- 给定旧 `final/`，它只作为行为和职责参考；活动代码不从 `final/` 导入，也不因旧文件较大而重新合并成 god module。
- 给定全量架构与行为测试，路径断言、import 边界、唯一连接池所有权和现有用户行为均保持通过；HTTP 除已记录的 lifespan maintenance 例外外不新增业务协调职责。

# Constraints and invariants

- feature 继续拥有业务事实与 use case；repository/platform/LLM/config/HTTP 只承担明确技术职责，不反向拥有业务规则。现有 HTTP lifespan maintenance 协调顺序是本 change 明确保留的唯一例外，不作为未来实现范式。
- `ConversationMessage`、`AgentRun`、LangGraph State/checkpoint、Memory facts 和 ContextProjection 的权威边界不因移动文件而改变。
- 最终 ContextProjection 由独立 `promptctx/` package 唯一拥有；memory 不拼装完整 Prompt，agent 不重新定义第二套 ContextBlock 或预算模型。
- 不以文件大小单独决定拆分。独立变化原因、独立消费者、测试隔离和依赖方向优先；同时避免只有转发或单个微小函数的预建模块。
- 活动生产文件不得超过 800 行；约 200--400 行是常规模块参考，不以无意义拆分满足行数。
- 不建立全项目 `domain/`、共享 `ports/` 或 catch-all `models.py`；任何跨 feature application coordinator 必须有唯一、真实的协调职责。
- package `__init__.py` 只提供稳定导出，不承载业务逻辑或自动发现 adapter。
- M06--M09 的最终文件名、子 package 和共享表面由各模块后续 Shape 决定，本 change 只冻结“不预建”和扩展方向。

# Decisions

- [用户确认] 目标布局不保留 `venagent/infra/`。
- [用户纠正] 目标目录必须包含独立 `promptctx/`；此前把“不新增统一 source_memory”推导为“继续把全部 ContextProjection 留在 agent/context.py”属于错误收敛，不再作为决定。
- [用户确认] M06--M09 先规划/参考，进入实际模块时再确定并生成文件。
- [用户确认] 本 change 停留在 Shape 讨论阶段，先参考 `final/` 讨论文件合并，不立即请求最终契约确认。
- [用户确认] 移除 `infra/` 后采用 `repo/`、`platform/`、`llm/`、`config/` 四个技术根，并把 security adapter 放入 `platform/security/`；`repo` 只承载 feature port adapter，`platform` 只承载共享资源与运行期技术能力。
- [用户确认] conversation 的标题规则与输入校验合并为 `conversation/rules.py`，不创建两个微小的 `title.py`/`validation.py`。
- [用户确认] 本 change 只从 `agent/runtime.py` 抽出已有独立消费者的 `observation.py`；scheduler/execution 保持在 runtime，待 M07 的真实 planner、interrupt、并行与重规划进入后再决定协作者和文件。
- [用户确认] temporary conversation/run adapter 与 PostgreSQL 对齐职责视图，拆为 `conversation.py`、`runs.py` 和薄 façade。
- [用户确认] 跨领域删除/回收循环本 change 保持在 `interfaces/http/app.py` 的 FastAPI lifespan 中，不新增根级 `maintenance.py` 或全局 `application/` package；该选择保持现有运行行为，但作为 HTTP transport 暂时承载应用协调顺序的已知边界例外记录，不推广为后续模块模式。
- [用户确认] 长期记忆采用 `memory/long_term/` 子包，至少以 `facts.py`、`policy.py`、`writer.py` 承载事实/来源值对象、候选与安全规则、事实写入行为；跨 short/long/G1 的 management、recall source、jobs、ports 与 façade 保持在 memory 根或对应的 promptctx 边界。`short_term.py` 当前保持单文件，不为目录对称创建子包。
- [用户确认] 当前 `memory/recall_provider.py` 按职责拆分：`memory/recall.py` 保留授权、生命周期、短期/长期/G1 候选与排序，`promptctx/recall_provider.py` 承担已合格 memory 候选到 ContextBlock 的 provider 适配；通用 ContextBlock、schema/policy、预算和 ModelCallContext 迁入 `promptctx/`，不再由 agent 定义。文件采用 `recall_provider.py` 命名，不使用 `source_recall.py` 或含义模糊的 `source_memory.py`。
- [仓库事实] 旧 `final/internal/memory/memory.py` 约 993 行，其中 `LongTerm` 同时承担缓存、存储加载、召回、embedding、整合和图协作；当前实现已将这些职责拆到 facts/types、write pipeline、management、recall provider 和 adapters，不能以旧类名直接判断应重新合并。
- [仓库事实] 当前 `memory/long_term.py` 约 95 行，除 `MemoryFact`/`MemorySource` 外还集中命令结果、health、settings 和 request snapshot 等跨职责读模型；其名称和模块说明与实际内容不一致。
- [仓库事实] 当前 `agent/runtime.py` 约 667 行、temporary conversation/run adapter 约 679 行、HTTP routes 约 474 行；它们存在可辨识职责段，但尚未超过 800 行硬上限。
- [仓库事实] 当前 `memory/recall_provider.py` 同时执行 memory 授权、短期窗口/摘要、长期/G1 权威召回和排序，并直接构造从 `agent/context.py` 导入的 ContextBlock；该文件混合了 memory 业务召回与 Prompt source 适配，形成 `memory -> agent` 依赖。
- [仓库事实] 旧 `final/internal/promptctx` 提供 assembler/context/schema/slot/source 与多个 source 文件，但其 assembler 使用字符预算、通用 slot/registry 和异常转空结果；当前实现已有更严格的整块 token 预算、required section、结构化 overflow 与确定性排序，目标只继承职责边界，不复制旧算法。
- [仓库事实] 当前 `MemoryService` 通过 `MemoryAuthorizationMixin -> MemoryManagementMixin -> MemoryWritePipelineMixin -> MemoryRecallProviderMixin` 多继承拼装公开 API。四个 mixin 隐式共享至少 `_store`、`_ownership`、`_graph_memory`、`_capabilities`、`_local_disabled`、`_now` 等宿主状态；`management.py` 还调用只由后续 write mixin 提供的 `_resolve_quarantine`，并直接导入 write pipeline 的私有 `_valid_until`。其正确性依赖 MRO 与未声明的私有宿主契约，不能由各文件自身类型边界证明。
- [用户确认] 保留 `MemoryService` 稳定公开 façade，但以显式组合替换 mixin 多继承。`MemoryAuthorizer`、`MemoryManager`、`LongTermWriter`、`MemoryRecall` 和 `MemoryJobs` 通过构造函数接收明确依赖，`MemoryService` 只做类型化委托并保持当前公开方法；`promptctx/recall_provider.py` 只依赖 MemoryRecall port，command adapter 只依赖管理/写入所需的最小 façade，job worker 只依赖 jobs port。不得把这些职责重新合并进 `service.py`。
- [仓库事实] 当前 `infra/platform/runtime.py` 的 `PersistenceRuntime` 同时持有 checkpointer、conversation/run store、ownership store、memory store 与数据库池，`build_persistence_runtime()` 还直接构造三类 feature adapter；若只改路径为 `platform/runtime.py`，会同时违反“platform 只拥有共享技术资源”和“bootstrap 是唯一装配点”。
- [仓库事实] 当前 `interfaces/http/routes.py` 注册 18 个 endpoint，横跨 health、identity/auth、conversation、run/SSE 和 Web UI；文件虽仅约 474 行，但已有多个独立 API 消费面与变化原因。
- [仓库事实] 当前 PostgreSQL 根 `row_mapping.py` 混合 ownership、conversation、message 与 run 映射；temporary memory 的 `row_mapping.py` 实际只包含 fact tombstone/redaction 与确认哈希逻辑，并不存在 row，后者名称与职责不符。
- [实现约束] `memory/ports.py` 文件可保留，但当前约 30 个方法的 `MemoryStore` Protocol 应按 fact/summary/job 等消费者拆成同文件内的窄 Protocol，并仅为完整 adapter 提供组合 Protocol；不得让显式组合后的所有职责对象继续依赖同一个宽接口。
- [用户确认] `platform/runtime.py` 改为 backend-neutral resources/status/lifecycle façade；PostgreSQL pool、schema validation 与 checkpointer 生命周期迁入 `platform/postgresql/runtime.py`，现有 PostgreSQL migration 迁入 `platform/postgresql/migrations.py`。`bootstrap.py` 根据技术资源构造 `repo/` adapters，temporary adapters/state 同样只在 bootstrap 装配，不放宽 platform 所有权，也不新增 application package。
- [用户确认] HTTP route 按现有消费面拆为 `routes/auth.py`、`routes/conversations.py`、`routes/runs.py` 与只提供稳定导出的 `routes/__init__.py`；health 与 Web UI 根路由保留在 `app.py`，`schemas.py` 保持单文件，HTTP 路径、状态码、schema 与 SSE 行为不变。
- [用户确认] adapter mapping 使用职责化命名：PostgreSQL ownership 映射收回 `ownership.py`，conversation/message/run 共享映射改为 `conversation_mapping.py`，temporary memory 的 tombstone/hash helper 改为 `fact_state.py`；`repo/postgresql/memory/row_mapping.py` 因确实负责数据库 row 映射而保留。
- [用户确认] 批准本 brief 中的 M01--M05 最终目标活动树作为整体项目目录基调；该批准冻结列出的 package/file 归属和依赖边界，不预建 M06--M09，也不等同于 Shape 最终契约确认。
- [用户确认] 确认最终 Shape 共享理解并批准进入 Build。重构代码应在授权、fencing、生命周期、降级与 composition 等非显然边界添加简短的“为什么”注释，不为显然代码增加逐行转述；README 的最终目录树应按批准示例为列出的目录与文件逐项注释职责，便于直接定位所有权。

# Target package layout for approval

以下是只覆盖当前 M01--M05 的最终目录审批版。注释中的“迁入/拆出/合并”描述本 change 的迁移来源；未列出的 M06--M09 目录与文件不会预建。

```text
venagent/
├─ __init__.py
├─ __main__.py
├─ bootstrap.py
├─ agent/
│  ├─ __init__.py
│  ├─ errors.py
│  ├─ graph.py
│  ├─ ports.py
│  ├─ runs.py
│  ├─ state.py
│  ├─ observation.py              # 从 runtime.py 拆出现有观察/订阅职责
│  └─ runtime.py                  # 保留调度、执行、恢复、取消与 façade
├─ conversation/
│  ├─ __init__.py
│  ├─ errors.py
│  ├─ models.py
│  ├─ ports.py
│  ├─ rules.py                    # 合并 title.py 与现有输入约束
│  └─ service.py
├─ ownership/
│  ├─ __init__.py
│  ├─ errors.py
│  ├─ models.py
│  ├─ ports.py
│  └─ service.py
├─ memory/
│  ├─ __init__.py
│  ├─ authorization.py            # MemoryAuthorizer + request snapshot
│  ├─ capabilities.py             # MemoryHealth/Settings + capability registry
│  ├─ command_adapter.py          # 命令解析 + MemoryCommandResult
│  ├─ errors.py
│  ├─ graph.py                    # 纯 G1 规则
│  ├─ graph_memory.py             # 跨 store 的 G1 应用服务，名称保持原样
│  ├─ jobs.py                     # MemoryJob + claim/dispatch/retry 行为
│  ├─ job_worker.py               # 仅 lifespan polling worker
│  ├─ management.py               # MemoryManager：查询、删除、确认与开关
│  ├─ ports.py
│  ├─ recall.py                   # MemoryRecall：授权后候选召回与排序
│  ├─ service.py                  # 稳定 façade，以显式组合委托
│  ├─ short_term.py               # 当前保持内聚单文件
│  └─ long_term/
│     ├─ __init__.py
│     ├─ facts.py                 # MemoryFact/Source/Page
│     ├─ policy.py                # 候选提取、资格、安全与有效期规则
│     └─ writer.py                # LongTermWriter：写入、版本化、隔离处理
├─ promptctx/
│  ├─ __init__.py
│  ├─ assembler.py                # 确定性收集、投影与 token 预算
│  ├─ context.py                  # ContextBlock/ModelCallContext/BudgetReport
│  ├─ errors.py
│  ├─ recall_provider.py          # 合格 memory 候选 -> ContextBlock
│  ├─ schema.py                   # SectionSpec/ProjectionPolicy/角色策略
│  └─ source.py                   # 类型化 ContextSource 合约与状态
├─ repo/
│  ├─ __init__.py
│  ├─ postgresql/
│  │  ├─ __init__.py
│  │  ├─ conversation.py
│  │  ├─ conversation_mapping.py  # conversation/message/run 共享映射
│  │  ├─ conversation_runtime.py  # conversation/run 的薄共享 façade
│  │  ├─ ownership.py              # 同时拥有 ownership row 映射
│  │  ├─ runs.py
│  │  └─ memory/
│  │     ├─ __init__.py
│  │     ├─ jobs.py
│  │     ├─ long_term.py
│  │     ├─ row_mapping.py
│  │     └─ short_term.py
│  ├─ temporary/
│  │  ├─ __init__.py
│  │  ├─ conversation.py          # 从 conversation_runtime.py 拆出
│  │  ├─ conversation_runtime.py  # 与 PostgreSQL 对齐的薄 façade
│  │  ├─ ownership.py
│  │  ├─ runs.py                  # 从 conversation_runtime.py 拆出
│  │  ├─ state.py
│  │  └─ memory/
│  │     ├─ __init__.py
│  │     ├─ graph.py
│  │     ├─ fact_state.py          # tombstone/redaction/确认哈希
│  │     ├─ jobs.py
│  │     ├─ long_term.py
│  │     ├─ short_term.py
│  │     └─ state.py
│  └─ neo4j/
│     ├─ __init__.py
│     └─ memory_graph.py
├─ platform/
│  ├─ __init__.py
│  ├─ errors.py
│  ├─ observability.py           # 从根 observability.py 迁入
│  ├─ runtime.py                 # backend-neutral 资源/状态/生命周期 façade
│  ├─ postgresql/
│  │  ├─ __init__.py
│  │  ├─ migrations.py           # PostgreSQL/LangGraph schema 迁移
│  │  └─ runtime.py              # pool、schema validation、checkpointer 生命周期
│  ├─ neo4j/
│  │  ├─ __init__.py
│  │  ├─ migrations.py
│  │  └─ runtime.py
│  └─ security/
│     ├─ __init__.py
│     ├─ passwords.py
│     └─ tokens.py
├─ llm/
│  ├─ __init__.py
│  ├─ config.py
│  ├─ factory.py
│  └─ providers.py
├─ config/
│  ├─ __init__.py
│  └─ loader.py
└─ interfaces/
   ├─ __init__.py
   └─ http/
      ├─ __init__.py
      ├─ app.py                   # 保留 lifespan maintenance 协调例外
      ├─ auth.py
      ├─ errors.py
      ├─ schemas.py
      ├─ streaming.py
      └─ routes/
         ├─ __init__.py           # 只提供稳定导出
         ├─ auth.py
         ├─ conversations.py
         └─ runs.py
```

M06--M09 只冻结扩展方向：M06 从 agent/LLM/platform security 与未来 tool/sandbox 边界扩展；M07 从 `agent/runtime.py` 的真实 planner/interrupt/parallel/replanning 消费者扩展；M08 通过新增自己的 `promptctx` source 接入 document/RAG；M09 根据真实 queue/operator 用例确定 package。上述名字均不是待创建文件清单。

# Open questions

- 当前无未决事项。

# Verification expectations

- 先以静态 import/AST 测试证明 feature 不依赖具体 adapter、HTTP 不访问数据库、所有 adapter 只由 `bootstrap.py` 装配。
- 增加静态与单元测试，证明 memory 不再导入 agent，promptctx 不读取数据库或拥有 memory 生命周期，agent 只消费 promptctx 的公开装配契约。
- 更新并运行 `tests/test_package_layout.py`，覆盖新路径、不存在 `infra/`、不预建 M06--M09、唯一连接池/checkpointer 资源所有权和文件规模。
- 运行现有 M01--M05 全量 pytest、Ruff（若可用）和 `compileall`；路径迁移不得降低现有行为基线。
- 对 temporary/PostgreSQL adapter 运行一致性测试，证明拆文件不改变事务、fencing、删除、记忆生命周期和异常语义。
- 对 HTTP route/lifespan 和 bootstrap 运行集成测试，证明应用启动、关闭、维护、SSE、memory 命令和健康状态行为保持。
- 人工复核全部受影响 canonical specs 和 README，不残留活动 `venagent/infra` 路径或与未来 M06--M09 空目录相冲突的要求；README 目录树中列出的目录与文件均带有简洁职责注释。
