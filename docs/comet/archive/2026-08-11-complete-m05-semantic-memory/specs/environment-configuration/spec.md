# 环境配置完整目标规格

## 1. 目标与唯一来源

VenAgent SHALL 使用不可变、严格校验的 `AppConfig` 作为 CLI、FastAPI、LLM adapter 与持久化 runtime 的唯一配置对象。部署配置来源 SHALL 仅为代码内安全默认值、仓库根 `.env` 与显式进程环境变量，优先级为：安全默认值 < `.env` < 显式进程环境变量。

`.env` SHALL 只作为本地开发便利并保持 Git 忽略；生产环境 SHOULD 通过进程环境或 Secret Manager 注入同名变量。应用 SHALL NOT 读取 YAML 配置，不再支持 `venagent/config/config.yaml`、`config.local.yaml` 或 `VENAGENT_CONFIG_PATH`。

## 2. 白名单变量

配置加载器 SHALL 只接受显式白名单，并把变量映射到 `server`、`persistence`、`auth` 与 `llm` 配置段：

- server：`SERVER__PORT`。
- persistence：`PERSISTENCE__ENABLED`、`PERSISTENCE__HOST`、`PERSISTENCE__PORT`、`PERSISTENCE__DATABASE`、`PERSISTENCE__USER`、`POSTGRES_PASSWORD`。
- auth：`AUTH__ISSUER`、`AUTH__AUDIENCE`、`AUTH__COOKIE_SECURE`、`AUTH__ALLOWED_ORIGINS_JSON`、`JWT_SECRET`。
- llm：既有 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_API_MODE`、`LLM_BASE_URL`、`LLM_ENDPOINT_URL`、`LLM_AZURE_ENDPOINT`、`LLM_AZURE_DEPLOYMENT`、`LLM_API_VERSION`、`LLM_REASONING_EFFORT`、`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`、`LLM_TIMEOUT`、`LLM_MAX_RETRIES`、`LLM_VERBOSITY`、`LLM_EXTRA_BODY_JSON`。
- memory extractor：可选的 `MEMORY_EXTRACTOR_PROVIDER`、`MEMORY_EXTRACTOR_API_KEY`、`MEMORY_EXTRACTOR_MODEL`、`MEMORY_EXTRACTOR_API_MODE`、`MEMORY_EXTRACTOR_BASE_URL`、`MEMORY_EXTRACTOR_ENDPOINT_URL`、`MEMORY_EXTRACTOR_AZURE_ENDPOINT`、`MEMORY_EXTRACTOR_AZURE_DEPLOYMENT`、`MEMORY_EXTRACTOR_API_VERSION`、`MEMORY_EXTRACTOR_TEMPERATURE`、`MEMORY_EXTRACTOR_MAX_TOKENS`、`MEMORY_EXTRACTOR_TIMEOUT`、`MEMORY_EXTRACTOR_MAX_RETRIES`、`MEMORY_EXTRACTOR_EXTRA_BODY_JSON`。全部为空时复用当前对话模型；仅设置 model 时继承主模型连接 profile 并覆盖模型名。
- embedding：通用 `EMBEDDING_API_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`，以及可选 `EMBEDDING_TIMEOUT`、`EMBEDDING_MAX_RETRIES`。该配置属于模型技术层，不使用 `MEMORY_EMBEDDING_*`；M05 首先消费，未来 M08 可以复用同一 adapter，但本 change 不创建 M08 业务文件。

空白值 SHALL 视为未设置。未知的包含双下划线的无前缀结构化变量 SHALL 快速失败，避免拼写错误被静默忽略；无关宿主环境变量不得透传到配置对象。旧 `VENAGENT_` 变量不是兼容输入，也不得影响配置。

## 3. 解析与校验

- 端口、token 上限与重试次数 SHALL 使用严格整数解析；temperature 与 timeout SHALL 使用有限浮点数解析；enabled 与 cookie_secure SHALL 只接受明确布尔值。
- `AUTH__ALLOWED_ORIGINS_JSON` SHALL 是字符串数组，`LLM_EXTRA_BODY_JSON` SHALL 是 JSON object；结构不符 SHALL 产生稳定 `ConfigError`。
- 配置字段仍由严格、冻结的 Pydantic model 执行范围、额外字段和跨字段校验；错误 SHALL 只报告字段路径与原因，不得回显秘密值、完整连接串、认证头或 `.env` 内容。
- `MEMORY_EXTRACTOR_*` SHALL 解析为不可变 extractor override。全部为空时明确选择当前对话模型；只有 `MEMORY_EXTRACTOR_MODEL` 时从已校验主模型 profile 派生并替换 model；一旦设置 extractor provider、凭据、URL 或 endpoint，则视为独立 provider 配置并严格校验所需字段，不得与主 profile 作未声明的逐字段拼接。
- embedding 的 URL、key、model SHALL 全部存在或全部为空；全部为空表示能力未配置，任一缺失表示显式配置错误。`EMBEDDING_API_URL` SHALL 是以 `/embeddings` 结尾的绝对 HTTP(S) endpoint，拒绝 query、fragment 和 userinfo；API key 只保存在 `SecretStr`，错误不得回显 URL 凭据、请求正文或向量。
- 测试显式传入 environment mapping 时 SHALL 完全隔离真实进程环境与仓库 `.env`，保证可重复性。
- `get_runtime_config` SHALL 在生产进程内缓存同一个只读快照，避免 CLI、bootstrap 和 adapter 分别读取配置。

## 4. PostgreSQL 配置边界

`PersistenceConfig` SHALL 从白名单变量生成数据库连接信息。密码 SHALL 只来自 `POSTGRES_PASSWORD`；仅当持久化显式启用且密码存在时才生成 `database_url`，用户名、密码与数据库名 SHALL 正确 URL 编码。

pytest 的真实 PostgreSQL 集成测试 SHALL 从 `TEST_DATABASE_URL` 读取隔离测试数据库连接，且不得连接开发数据库 `venagent`。配置对象只负责校验和生成秘密包装的 DSN，不创建连接池、session 或 HTTP dependency。`platform/runtime.py` SHALL 接收配置并选择 backend，`platform/postgresql/runtime.py` SHALL 成为 PostgreSQL pools、schema validation 与 checkpointer 生命周期的唯一技术所有者；feature adapter 不得直接读取环境变量，所有 repo adapter 只接收 `bootstrap.py` 注入的资源。

## 5. 文件、依赖与文档迁移

- 删除活动包中的 `venagent/config/config.yaml` 与 `config.local.yaml` 示例，不再把 YAML 配置作为 package data。
- 删除配置 loader 的 YAML 读取、深合并、秘密键扫描和 `VENAGENT_CONFIG_PATH` 分支；若无其他活动运行时用途，删除 PyYAML 依赖。
- `.env.example` SHALL 列出全部受支持变量、开发默认建议和秘密占位符，不得包含真实凭据；`.env` 与 `.env.example` 的每个变量均有紧邻的中文用途说明。
- `.env.example` SHALL 明确区分 `LLM_*` 主对话配置与可选 `MEMORY_EXTRACTOR_*` override，并说明未配置时复用当前对话模型、只配置 model 时继承连接参数。
- `.env.example` SHALL 列出通用 `EMBEDDING_*` 变量和无秘密占位符，不硬编码任何厂商 endpoint 或真实 key；仓库根 `.env` 继续被 Git 忽略。
- README、Compose、测试和包布局文档 SHALL 只描述 `.env`/进程环境配置，不再建议编辑 YAML 或使用 `VENAGENT_` 环境变量。
- canonical `configuration-management` 的 YAML 契约 SHALL 由本规格替代；历史归档和内容寻址 evidence 不作为活动代码清理对象。

## 6. 验收

- 无 YAML 文件时，默认配置、`.env` 配置和显式环境覆盖均可重复加载，且显式环境具有最高优先级。
- 所有白名单字段的正常、空白、非法类型、非法范围、非法 JSON、未知无前缀结构化键与秘密不回显测试通过；旧 `VENAGENT_` 名称不会配置应用。
- LLM 离线选择与真实 provider 严格校验保持原有行为，唯一变化是 server、persistence、auth 与测试数据库变量移除 `VENAGENT_` 前缀。
- extractor override 的空白复用、model-only 派生、完整独立 provider、非法混合、缺少凭据和秘密不回显测试通过；证明选择结果严格遵守上述三种模式。
- embedding 配置的全空 disabled、完整配置、部分配置、URL 后缀、超时/重试范围和秘密不回显测试通过；M05 adapter 与未来消费者不得自行读取环境变量。
- PostgreSQL 启用、缺少密码、特殊字符编码和 bootstrap 注入测试通过；任何 feature adapter 都不自行读取环境或构建连接资源。
- 运行时不再导入 PyYAML，包数据不再包含 YAML 配置，README 与 `.env.example` 不再出现活动 `VENAGENT_` 配置指引。
