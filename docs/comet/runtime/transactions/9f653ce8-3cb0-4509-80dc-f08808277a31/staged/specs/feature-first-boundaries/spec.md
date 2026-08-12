# Feature-first Boundaries 完整目标规格

## 1. 目标

VenAgent SHALL 保持 feature-first Python/Vue 结构。根级业务目录表达能力所有权，`infra/`、`interfaces/` 和 `bootstrap.py` 表达明确技术边界；不得再混用 feature、adapter、transport 或全局 layer-first 目录。

本规格继承原 `feature-first-package-layout` 的能力所有权与依赖约束，并补充“职责不混用”和业务命名规则。目录调整只服务已存在能力，不为 M06--M09 预建空 package、共享层或 adapter。

## 2. Python 能力边界

- `conversation/` 拥有 Conversation、ConversationMessage、对话标题、消息/run 创建协调、对话查询/删除和 conversation 消费方 ports。
- `agent/` 拥有 LangGraph State、graph、runtime contract、AgentRun lifecycle、worker/recovery、ContextProjection 和 model/run ports。
- `ownership/` 拥有 owner/user/session、RunGrant/ExecutionAuthorization、身份错误与 ownership 消费方 ports。
- `memory/` 拥有 M05 short-term、long-term、G1、来源资格、写入、召回、管理、授权、策略、health 和 memory 消费方 ports。
- `infra/` 只实现具体 adapter、配置、迁移、连接池、checkpointer、LLM provider 和安全技术能力；不得承载 feature use case。
- `interfaces/http/` 只拥有 FastAPI 依赖、Pydantic schema、HTTP 错误映射、SSE transport 与路由；不得拥有业务事实或直接写数据库。
- `bootstrap.py` 是唯一 composition root，显式装配 stores、checkpointer、services、runtime、lifespan 和启动报告。

## 3. Feature 内部组织

- feature package 内可以同时存在领域规则、用例和消费方 port，但文件名和依赖必须表达真实职责，不得通过全项目 `domain/`、`application/`、`ports/` 目录再次分层。
- 小型且内聚的 feature 可以保留 `models.py`、`service.py`、`ports.py`、`errors.py`；复杂 feature 必须按业务概念继续拆分，不得机械复制四件套。
- `memory/` SHALL 使用 `short_term.py`、`long_term.py`、`graph.py`、`recall_provider.py`、`write_pipeline.py`、`management.py` 等业务文件，不保留 catch-all `models.py` 或巨型 `service.py`。
- `agent/context.py` 是最终 ContextProjection 与预算权威；`memory/recall_provider.py` 只提供已授权的记忆候选。
- `ConversationMessage` 只由 conversation 拥有；memory short-term 可以消费消息只读值，不维护第二份消息事实。
- `automatic_title` 属于 conversation 规则，不得放在 infra adapter。

## 4. Ports 与错误

- 各 feature 通过自己的消费方 Protocol 依赖存储、模型、时钟、授权和通知；infra 实现这些 ports。
- `conversation/ports.py`、`agent/ports.py`、`ownership/ports.py`、`memory/ports.py` 分别定义本 feature 的 adapter 安全错误，不得借用 `conversation.ports.StoreError` 作为全项目错误。
- `ConversationStore` 与 `RunStore` SHALL 分离；不得通过 `RuntimeStore(RunStore, Protocol)` 把 conversation 与 agent 重新聚合。
- `infra/platform/errors.py` 只承载迁移、连接池、schema compatibility 等平台级错误；不得成为 feature domain/application 错误基类。
- conversation、agent、ownership、memory 的领域错误各自稳定映射到 HTTP；不得创建根级 catch-all `errors.py`。

## 5. Infrastructure 布局

```text
venagent/
├── agent/
├── conversation/
├── memory/
├── ownership/
├── infra/
│   ├── config/
│   ├── llm/
│   ├── security/
│   ├── memory/
│   │   ├── temporary/
│   │   └── postgresql/
│   └── platform/
│       ├── runtime.py
│       ├── migrations.py
│       ├── errors.py
│       ├── temporary/
│       └── postgresql/
├── interfaces/http/
├── bootstrap.py
└── __main__.py
```

- `infra/memory/` 只实现 M05 ports，按 backend 和 short-term/long-term/graph/jobs 职责拆分。
- `infra/platform/` 只实现 ownership、conversation、run 与平台 runtime；现有含义模糊的 `memory.py` 和聚合式 `postgres.py` 必须拆除。
- temporary 与 PostgreSQL 可以拥有同名 adapter 文件，因为父目录明确表示后端；文件内不得复制业务规则。
- 具体 adapter 只在 `bootstrap.py` 装配；feature、HTTP route 和 package `__init__.py` 不得自动发现 adapter。
- 多个 `postgresql/` 子目录 SHALL 只表示按 feature port 拆分的 SQL adapter，不表示多套数据库 runtime。所有运行期 PostgreSQL adapter SHALL 通过构造函数接收 `infra/platform/runtime.py` 创建的共享同步连接池，不得自行读取配置、构造 DSN、创建或关闭连接池。
- `infra/platform/runtime.py` SHALL 是应用运行期连接资源的唯一所有者：负责同步业务池和官方 LangGraph async checkpointer 池的创建、注入、健康状态与关闭。async checkpointer 因官方异步 API 使用独立池不构成第二套 feature persistence ownership。
- 显式 migration CLI MAY 为执行 DDL 使用短生命周期直连，但普通应用启动 SHALL NOT 执行 DDL；迁移直连不得被 feature adapter 复用为请求期连接工厂。
- 当前 psycopg repository 架构 SHALL NOT 引入 SQLAlchemy session factory 或 FastAPI `get_db`。HTTP route 只依赖 feature service/runtime facade，不得 checkout 原始连接或控制事务。

## 6. 依赖方向

- agent、conversation、ownership、memory 不得导入 FastAPI、psycopg、具体 provider SDK或 `venagent.infra` adapter。
- infra 可以导入 feature models/ports 来实现契约，但不得反向调用 feature use case。
- interfaces 只调用 feature services/runtime facade；不得直接导入具体 infra store、配置 loader 或 provider factory。
- agent 不拥有 owner/session/credential 事实；conversation 不解析 Cookie；ownership 不执行 LangGraph；memory 不拥有最终 prompt 投影。
- checkpointer 配置只由 agent 公开 helper 产生；其他 package 不得散布 `thread_id` 拼装或查询私有表。

## 7. 前端、CLI 与兼容

- 保持根目录 `web/` 的 Vue 3 feature-module 基线，不迁入 Python package。
- `python -m venagent` 和显式 migration 命令保持可用；普通启动不执行 DDL。
- HTTP schema、SSE、命令、数据库 schema 和公开根包导出保持兼容；配置来源按本 change 的环境配置规格迁移，不再保持 YAML 兼容。
- `final/` 继续作为 legacy/reference，不属于活动 package 布局。

## 8. 验收

- 根级活动 Python 目录保持 feature-first，不新增全项目 `domain/`、`application/`、`infrastructure/` 或共享 `ports/` 层。
- 架构测试证明 feature 不依赖具体 adapter、infra 不承载 use case、interfaces 不承载业务事实，bootstrap 是唯一装配点。
- memory 不再形成 god service/catch-all models；platform 不再存在含义模糊的 `memory.py` 或聚合式 `postgres.py`。
- 各 feature port 错误和领域错误边界明确，`conversation.ports.StoreError` 不再被跨 feature 复用。
- 静态架构测试证明连接池构造只存在于平台 runtime，feature PostgreSQL adapter 只接收注入资源，HTTP 层不存在 `get_db` 或原始数据库访问。
- 全量 Python/前端测试、compileall、类型/静态检查和 PostgreSQL 集成验证使用新路径通过；README 和 package layout 测试同步更新。
