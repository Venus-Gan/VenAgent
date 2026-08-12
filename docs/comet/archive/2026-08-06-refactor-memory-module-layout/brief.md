# Outcome

重新校准 VenAgent 的整体 feature-first 边界，而不是只移动 memory 文件：保留 `venagent/memory/` 作为 M05 能力中心，以 `short_term.py` 与 `long_term.py` 分离短期和长期记忆规则；让 conversation、agent、ownership、memory、infra 和 interfaces 各自拥有明确职责，消除定义类集中、巨型 service、含义模糊 adapter、跨能力错误错位和 feature/技术层混放。

# Scope

- `venagent/memory/`：按 short-term、long-term、graph、recall provider、write pipeline、management、authorization、policy、health、commands 和 capability ports 重组；不再保留 catch-all `models.py` 或巨型 `service.py`。
- `venagent/conversation/`、`venagent/agent/`、`venagent/ownership/`：保持根级 feature package；将泛化 `models.py`/`service.py` 按实际业务概念和 use case 拆分，禁止承载其他 feature 的事实或 port。
- 各 feature 的 `ports.py` 只定义本 feature 消费的 Protocol 和安全 adapter 错误；不再从 `conversation.ports` 借用全局 `StoreError`，也不新增根级共享 `ports/`。
- `venagent/infra/memory/`：按 `temporary/` 与 `postgresql/` 后端拆分 `long_term.py`、`short_term.py`、`graph.py` 和 `jobs.py` adapter，另设后端专属 `state.py`/`row_mapping.py`；不得把 M05 业务规则塞回 adapter。
- `venagent/conversation/`：继续拥有 `ConversationMessage` 权威和 conversation 用例；短期记忆算法位于 `venagent/memory/short_term.py`，不复制消息存储。
- `venagent/agent/context.py`：继续拥有纯 `ContextProjection` 和预算投影；memory 只通过 `venagent/memory/recall_provider.py` 提供授权后的 `ContextBlock` 候选，不再创建 `memory/context.py`。
- `venagent/infra/platform/`：保留平台基础设施目录；移除含义模糊的 `memory.py` 和聚合式 `postgres.py`，按 `temporary/` 与 `postgresql/` 后端拆分 adapter。
- `venagent/infra/platform/runtime.py`：作为数据库连接资源的唯一运行时所有者，集中创建、注入和关闭 PostgreSQL 同步连接池与官方 LangGraph checkpointer 所需的异步连接池；feature adapter 只能消费注入的池，不得自行创建连接池、session factory 或 HTTP `get_db` 依赖。
- 配置来源统一为代码内安全默认值、仓库根 `.env` 和显式进程环境变量；移除 `venagent/config/config.yaml`、`config.local.yaml`、`VENAGENT_CONFIG_PATH`、PyYAML 运行时依赖与包数据声明，并把完整白名单写入 `.env.example`。
- `venagent/conversation/title.py`：接收当前误放在平台 adapter 中的 `automatic_title` 业务规则。
- `venagent/interfaces/http/` 与根级 `bootstrap.py`：分别保持 transport 与唯一 composition root，不承载业务事实。
- 实现时为授权/fencing、来源资格、事务顺序、删除 generation、降级边界和图关系重放添加简洁的“为什么”注释；不添加显然赋值的逐行注释。
- 相关 import、测试和模块布局契约测试。

# Non-goals

- 不改变 M05 的用户可见行为、命令语义、HTTP schema、数据库 schema、迁移、授权规则、图关系规则或性能预算；配置来源从 YAML 迁移到环境变量除外。
- 不新增前端页面或未来能力的目录/抽象。
- 不修改 `final/internal/memory/memory.py` 等 legacy/reference 代码。
- 不把 Mem0、OpenViking、TaskMem、M07/M08 业务逻辑加入平台 adapter。
- 不把平台 adapter 重命名误当作 M05 短期记忆实现；平台层仍只负责 owner/conversation/run 状态。
- 不把 `ConversationError` 与 `MemoryError` 合并为跨域基类；各 feature 使用自己的稳定错误族和 port 错误。
- 不引入全项目 `domain/`、`application/` 或共享 `ports/` 目录；保持 feature-first，依靠文件职责和依赖规则防止混用。
- 不向 FastAPI route 暴露原始数据库连接，不引入 SQLAlchemy `sessionmaker`/`get_db`，也不把每个 `postgresql/` adapter 目录解释为一套独立数据库 runtime。
- 不复制 AGI-saber 的 Go 包结构、数据库表结构或具体聚合实现；只采用其短期/长期、写入、召回 source、context assembler、repository 的职责分离思想。

# Acceptance examples

- 活动实现中不再存在 `venagent/infra/platform/memory.py` 或聚合式 `venagent/infra/platform/postgres.py`；temporary/PostgreSQL 两种平台 adapter 与现有调用链行为一致。
- `venagent/memory/short_term.py` 与 `venagent/memory/long_term.py` 分别承载短期窗口/摘要规则和长期事实/来源/生命周期规则；不存在 catch-all `models.py`。
- `venagent/memory/recall_provider.py` 能作为 provider 接入 `agent/context.py`，但不拥有最终预算投影；`write_pipeline.py` 不接受 assistant 自由文本作为长期来源。
- conversation、agent、ownership、memory 各自定义 port 错误；memory/platform 不再导入 `conversation.ports.StoreError`。
- conversation service 显式消费 `ConversationStore` 与 `RunStore`，不再依赖继承 `RunStore` 的聚合 `RuntimeStore`。
- M05 现有行为回归全部通过，PostgreSQL 集成仍按原方式可运行。
- 活动 Python 包保持 feature-first；feature 不导入具体 infra adapter，infra 不承载 feature use case，interfaces 不承载业务事实，bootstrap 是唯一装配点。
- 全部受支持的服务器、PostgreSQL、认证与 LLM 配置均可由 `.env`/显式环境变量表达；显式环境覆盖 `.env`，未知的结构化 `VENAGENT_*__*` 键和非法类型均快速失败且不泄露秘密。
- 所有 PostgreSQL feature adapter 由唯一平台 runtime 注入共享同步连接池；仅官方异步 LangGraph checkpointer 使用同一 runtime 所有的独立异步池，显式 migration CLI 使用短生命周期直连且普通启动不执行 DDL。

# Constraints and invariants

- `venagent/infra/platform/` 实现 PostgreSQL/temporary 业务 adapter、显式 schema migration、官方 checkpointer 装配与启动模式选择，不拥有 conversation/agent/ownership 用例。
- `venagent/infra/platform/runtime.py` 是应用运行期数据库连接资源的唯一 composition owner；adapter 构造函数只接收池，`interfaces/http/` 不得定义 `get_db` 或直接 checkout 连接。
- 多个 `postgresql/` 子目录只按 feature port 分隔 SQL adapter；它们共享 runtime 注入的连接资源，不得各自读取配置、拼接 DSN 或管理池生命周期。
- 每个 feature 的 port 错误只服务该 feature；平台级迁移/连接错误留在 `infra/platform/errors.py`，不伪装成 conversation 错误。
- 业务用例不依赖具体 adapter，adapter 不承载 HTTP/命令解析或长期记忆事实。
- 现有 `feature-first-package-layout` 继续有效，并由本 change 补充“禁止 feature/infra/interfaces 职责混用”和业务命名要求。
- 公开类名、函数签名、返回结构、异常语义、序列化和事务边界保持不变；内部拆分必须可回滚且无数据迁移。
- 文件名必须表达职责，禁止用无区分的 `memory.py` 作为活动 adapter 实现文件；复杂 feature 不得依赖 catch-all `models.py` 或巨型 `service.py` 掩盖真实职责。

# Decisions

- 保留 `venagent/infra/platform/` 作为平台基础设施边界，不改回含义不完整的 `persistence/`；非持久降级实现统一使用已有运行模式术语 `temporary`，不使用易与 M05 混淆的 `memory` 或含义不充分的 `in_memory`。
- 平台类型迁移为 `TemporaryPlatformState`、`TemporaryOwnershipStore`、`TemporaryConversationRuntimeStore` 与 `PostgresConversationRuntimeStore`；`_memory_runtime` 改为 `_build_temporary_runtime`。
- 保留 `venagent/memory/` 作为 M05 能力中心，不采用全项目 `domain/application/infrastructure` 重排，也不采用此前 `personal_memory` 命名。
- feature 内以业务文件表达职责：`short_term.py`、`long_term.py`、`graph.py`、`recall_provider.py`、`write_pipeline.py`、`management.py`；具体 adapter 只位于 `infra/memory/`。
- `memory/short_term.py` 以 `ConversationMessage` 为唯一消息权威；`memory/long_term.py` 只管理 owner 私有长期事实和来源；`memory/recall_provider.py` 负责候选组合，`agent/context.py` 负责最终投影。
- `recall_provider.py` 取代此前含义不清的 `memory/context.py`，避免与 `agent/context.py` 产生“谁负责最终上下文”的错误暗示。
- `conversation/errors.py` 只保留对话输入、生命周期和幂等错误；`memory/errors.py` 只保留记忆授权、策略、游标、删除和生命周期错误；`MemoryInvalidCommand` 归入 `memory/commands.py` 的命令解析错误；运行与投影错误归入 `agent/errors.py`。
- `conversation.ports` 不再定义或导出全局 `StoreError`，也不再以继承方式聚合 `RunStore`；conversation service 同时接收 conversation port 与 agent run port，platform runtime 负责组合 adapter。
- 配置统一采用白名单环境变量：本地 `.env` 只是开发便利，生产使用显式进程环境或 Secret Manager；代码内只保留安全默认值，删除 YAML 配置层和 `VENAGENT_CONFIG_PATH`。
- psycopg 直接仓储模式不引入 SQLAlchemy session 或 FastAPI `get_db`；同步业务 adapter 共用一个池，LangGraph 官方 async saver 因异步 API 使用独立异步池，但两者都由同一 platform runtime 创建和关闭。显式 migration CLI 可短暂直连数据库，是普通应用 runtime 之外的管理入口。
- 代码注释是实现质量要求：只在非显然的安全边界、事务/发布顺序、并发 fencing、降级和来源治理处解释原因。

# Open questions

- 已确认：保留 `infra/platform/` 作为平台基础设施边界，按 `temporary/`、`postgresql/` 拆分 adapter，并把 `automatic_title` 迁回 `conversation` 所有权。
- 已确认：M05 保留 `venagent/memory/` 能力中心，以 short/long/graph/recall/write/management/authorization/policy/ports/errors/health 形成职责边界；不采用此前 `personal_memory` 目录提案。
- 已确认：实现阶段必须保留关键设计原因注释；本轮只写入契约，不开始生产代码实现。
- 已确认：继续采用 feature-first，不进行全项目四层目录重排；通过 feature 所有权、业务文件命名和依赖规则解决混用。
- 已确认：移除 `config.yaml`/`config.local.yaml` 混合配置，全部部署配置改由 `.env` 与显式进程环境变量提供。

# Verification expectations

- 运行 memory 相关 pytest 及完整项目 pytest，至少保持 M05 Verify 的 154 个测试基线。
- 运行 Ruff（若已安装）、`compileall`、模块导入检查和 PostgreSQL 集成测试；未安装工具如实记录。
- 增加或更新布局/导出契约测试，并进行针对循环依赖、文件规模、事务和异常边界的人工复核。
- 增加环境变量白名单、解析、覆盖优先级、秘密不回显、数据库 URL 编码以及“不存在重复连接池工厂/HTTP `get_db`”的契约测试。
