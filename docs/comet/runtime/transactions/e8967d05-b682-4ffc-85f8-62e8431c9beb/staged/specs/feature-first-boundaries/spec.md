# Feature-first Boundaries 完整目标规格

## 1. 目标

VenAgent SHALL 保持 feature-first Python/Vue 结构。根级 feature package 表达业务能力所有权，`repo/`、`platform/`、`llm/`、`config/`、`promptctx/`、`interfaces/` 和 `bootstrap.py` 表达各自明确边界；活动实现中不得存在含义过宽的 `venagent/infra/`，也不得混用 feature、adapter、transport 或全局 layer-first 目录。

本规格继承原 `feature-first-package-layout` 的能力所有权与依赖约束，并补充“职责不混用”和业务命名规则。目录调整只服务已存在能力，不为 M06--M09 预建空 package、共享层或 adapter。

## 2. Python 能力边界

- `conversation/` 拥有 Conversation、ConversationMessage、对话标题、消息/run 创建协调、对话查询/删除和 conversation 消费方 ports。
- `agent/` 拥有 LangGraph State、graph、runtime contract、AgentRun lifecycle、worker/recovery 和 model/run ports；它消费但不拥有通用 ContextProjection 契约。
- `ownership/` 拥有 owner/user/session、RunGrant/ExecutionAuthorization、身份错误与 ownership 消费方 ports。
- `memory/` 拥有 M05 short-term、long-term、G1、来源资格、写入、召回、管理、授权、策略、health 和 memory 消费方 ports。
- `promptctx/` 拥有 `ContextBlock`、`ModelCallContext`、`BudgetReport`、投影 schema/policy、类型化 source contract 与纯装配；它不读取数据库、不拥有 memory 生命周期或 agent State。
- `repo/` 只实现 conversation、run、ownership、memory 等 feature 消费方 port 的具体 adapter；不得承载 feature use case、连接资源生命周期或 HTTP 行为。
- `platform/` 只实现共享技术资源、schema migration、checkpointer、可观测性与安全 adapter；不得构造 feature adapter 或拥有业务事实。
- `llm/` 只实现模型配置标准化、provider 与 invoker factory；`config/` 只实现应用配置加载与校验。
- `interfaces/http/` 只拥有 FastAPI 依赖、Pydantic schema、HTTP 错误映射、SSE transport 与路由；不得拥有业务事实或直接写数据库。
- `bootstrap.py` 是唯一 composition root，显式装配 stores、checkpointer、services、runtime、lifespan 和启动报告。

## 3. Feature 内部组织

- feature package 内可以同时存在领域规则、用例和消费方 port，但文件名和依赖必须表达真实职责，不得通过全项目 `domain/`、`application/`、`ports/` 目录再次分层。
- 小型且内聚的 feature 可以保留 `models.py`、`service.py`、`ports.py`、`errors.py`；复杂 feature 必须按业务概念继续拆分，不得机械复制四件套。
- `memory/` SHALL 使用 `short_term.py`、`long_term/`、`graph.py`、`graph_memory.py`、`recall.py`、`jobs.py`、`management.py` 等真实职责文件，不保留 catch-all `models.py`、伪装完整长期实现的值对象文件或巨型 `service.py`。
- `promptctx/context.py` 与 `promptctx/schema.py` 是通用 ContextProjection、预算和策略权威；`memory/recall.py` 只返回授权、生命周期与相关性合格的记忆候选，`promptctx/recall_provider.py` 只把这些候选适配为 `ContextBlock`。
- `ConversationMessage` 只由 conversation 拥有；memory short-term 可以消费消息只读值，不维护第二份消息事实。
- `automatic_title` 属于 conversation 规则，不得放在 infra adapter。

## 4. Ports 与错误

- 各 feature 通过自己的消费方 Protocol 依赖存储、模型、时钟、授权和通知；`repo/`、`platform/` 与 `llm/` 的具体 adapter 实现相应 ports。
- `conversation/ports.py`、`agent/ports.py`、`ownership/ports.py`、`memory/ports.py` 分别定义本 feature 的 adapter 安全错误，不得借用 `conversation.ports.StoreError` 作为全项目错误。
- `ConversationStore` 与 `RunStore` SHALL 分离；不得通过 `RuntimeStore(RunStore, Protocol)` 把 conversation 与 agent 重新聚合。
- `platform/errors.py` 只承载迁移、连接池、schema compatibility 等平台级错误；不得成为 feature domain/application 错误基类。
- conversation、agent、ownership、memory 的领域错误各自稳定映射到 HTTP；不得创建根级 catch-all `errors.py`。

## 5. 技术边界布局

```text
venagent/
├── agent/
├── conversation/
├── memory/
├── ownership/
├── promptctx/
├── repo/
│   ├── temporary/
│   ├── postgresql/
│   └── neo4j/
├── platform/
│   ├── runtime.py
│   ├── observability.py
│   ├── postgresql/
│   ├── neo4j/
│   └── security/
├── llm/
├── config/
├── interfaces/http/
├── bootstrap.py
└── __main__.py
```

- `repo/*/memory/` 只实现 M05 ports，按 backend 和 short-term/long-term/graph/jobs 职责拆分；Neo4j 的 M05 graph adapter 位于 `repo/neo4j/memory_graph.py`。
- `repo/temporary/` 与 `repo/postgresql/` 分别实现 ownership、conversation、run 与 memory adapters；不得把这些 adapter 放回 `platform/`。
- temporary 与 PostgreSQL 可以拥有同名 adapter 文件，因为父目录明确表示后端；文件内不得复制业务规则。
- 具体 adapter 只在 `bootstrap.py` 装配；feature、HTTP route 和 package `__init__.py` 不得自动发现 adapter。
- `repo/postgresql/` 表示按 feature port 拆分的 SQL adapter，`platform/postgresql/` 只表示 PostgreSQL 技术资源和 migration，两者不得混用。所有运行期 PostgreSQL adapters SHALL 通过构造函数接收共享同步连接池，不得自行读取配置、构造 DSN、创建或关闭连接池。
- `platform/runtime.py` SHALL 只提供 backend-neutral resources/status/lifecycle façade；`platform/postgresql/runtime.py` 负责同步业务池和官方 LangGraph async checkpointer 池的创建、schema 只读校验与关闭。它们不得直接构造 conversation、run、ownership 或 memory adapter。
- `bootstrap.py` SHALL 根据 platform resources 显式构造并组合 `repo/` adapters、feature services、agent runtime 与 HTTP lifespan；temporary state/adapters 同样只在这里装配。
- 显式 migration CLI MAY 为执行 DDL 使用短生命周期直连，但普通应用启动 SHALL NOT 执行 DDL；迁移直连不得被 feature adapter 复用为请求期连接工厂。
- 当前 psycopg repository 架构 SHALL NOT 引入 SQLAlchemy session factory 或 FastAPI `get_db`。HTTP route 只依赖 feature service/runtime facade，不得 checkout 原始连接或控制事务。

## 6. 依赖方向

- agent、conversation、ownership、memory、promptctx 不得导入 FastAPI、psycopg 或具体 adapter；memory 不得反向导入 agent。
- repo 可以导入 feature models/ports 来实现契约，但不得反向调用 feature use case；platform 不得导入 repo 或构造 feature adapter。
- interfaces 只调用 feature services/runtime façade；不得直接导入具体 repo store、配置 loader、数据库资源或 provider factory。
- agent 不拥有 owner/session/credential 事实；conversation 不解析 Cookie；ownership 不执行 LangGraph；memory 不拥有最终 prompt 投影；promptctx 不拥有授权和 lifecycle 权威事实。
- checkpointer 配置只由 agent 公开 helper 产生；其他 package 不得散布 `thread_id` 拼装或查询私有表。

## 7. 前端、CLI 与兼容

- 保持根目录 `web/` 的 Vue 3 feature-module 基线，不迁入 Python package。
- `python -m venagent` 和显式 migration 命令保持可用；普通启动不执行 DDL。
- HTTP schema、SSE、命令、数据库 schema 和公开根包导出保持兼容；配置来源按本 change 的环境配置规格迁移，不再保持 YAML 兼容。
- `final/` 继续作为 legacy/reference，不属于活动 package 布局。

## 8. 验收

- 根级活动 Python 目录保持 feature-first，不新增全项目 `domain/`、`application/`、`infrastructure/` 或共享 `ports/` 层。
- 架构测试证明 feature 不依赖具体 adapter、repo/platform 不承载 use case、interfaces 不承载业务事实，bootstrap 是唯一装配点，且活动树不存在 `venagent/infra/`。
- memory 不再形成 god service/catch-all models；platform 不再存在含义模糊的 `memory.py` 或聚合式 `postgres.py`。
- 各 feature port 错误和领域错误边界明确，`conversation.ports.StoreError` 不再被跨 feature 复用。
- 静态架构测试证明连接池构造只存在于平台 runtime，feature PostgreSQL adapter 只接收注入资源，HTTP 层不存在 `get_db` 或原始数据库访问。
- 全量 Python/前端测试、compileall、类型/静态检查和 PostgreSQL 集成验证使用新路径通过；README 和 package layout 测试同步更新。
