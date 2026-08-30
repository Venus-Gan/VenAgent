---
wayfinder: ticket
id: config-yaml-migration
title: config 全量迁移与前端设置界面（.env → config.yaml）
labels: [wayfinder:task]
blocked_by: []
status: resolved
claimed_by: captain
resolved_comment: 用户逐块拍板 12 项（3 批）+ 热重载影响面讲解后拍板重启生效；Resolution 已写入执行设计（4 阶段）与验证方案。map.md Decisions so far 已同步。
---

## Question

把「抛弃并删除 .env、配置全靠 config.yaml」落地为可执行方案与验证（方向已由用户在 `tradeoffs-review` 全模块 grilling 拍板，本票只做执行设计与验证，不再回改方向）：

- `config.yaml`（gitignore，含真实 key，永不进 git）+ `config.example.yaml`（跟踪模板，敏感字段占位符）+ 启动装配时缺失则从模板复制生成。
- 全量迁移 9 区块（`loader.py:265-274` AppConfig）：llm / memory_extractor / embedding / persistence(PG) / neo4j / auth(JWT) / invocation(加密 key) / sandbox / server；github(GITHUB_TOKEN，bootstrap.py:206) 与 mcp 凭据（credential_ref，mcp/client.py:604）落点。
- 前端设置界面：LLM key / LLM URL / API 协议（Anthropic | Responses | completions 三选一）/ 思考强度三档（低/中/高，按协议原生映射：Anthropic=extended thinking+budget、OpenAI 系=reasoning_effort、completions 不支持则降级无思考）；后端 settings 接口读写 config.yaml（git 忽略，diff 干净）。
- 环境变量轻量覆盖（env > config.yaml）；容器编排 compose.yaml 保留独立 infra 文件（不并入 config.yaml）。
- loader 重构：YAML 解析 + fail-fast 白名单（修复 `loader.py:398-404` 静默忽略）；现有 ENV_FIELDS 映射表（loader.py:288 起）转 YAML schema；llm 装配收敛为三协议（providers.py:24-68 已支持，无需新 adapter）。

参考：`tickets/取舍原则复核.md` 结案第 8 条、`docs/wayfinder/assets/tradeoffs-review-synthesis.md`、AGI-saber 的 config.yaml(+config.docker.yaml)、final/config/config.yaml + final/docker-compose.yml。

Resolve 标准：.env 删除后系统可全 config.yaml 启动；真实 key 不进 git（gitignore 校验）；前端设置界面可用且写 config.yaml；env 仍可覆盖。

## Context（现状调查 759fed45 → assets/config-现状调查.md，2025-07 快照）

- **前端**：无 UI 组件库/axios（仅 vue3+pinia+vue-router+手写 CSS，web/src/style.css 432 行）；路由仅 2 页（/ ChatWorkspace、/control ControlPanel）；HTTP 统一经 modules/ownership/store.ts:85-96 apiFetch（原生 fetch，Bearer access token 内存态+credentials include+401 自动 refresh）；**无「设置」页面/入口**（grep 零命中）。
- **后端**：routes 4 组聚合注册（auth/control/conversations/runs，routes/__init__.py:24-50，app.py:295-309）；**无全局 auth Depends**——每个 handler 手动 `current_actor(request, ownership)`（interfaces/http/auth.py:22-23）+写操作 require_origin；**无任何 config/settings 端点**（配置运行时不可读改）。
- **游离 env 读取 7 处**：loader.py:373（合并入口）；llm/config.py:170（LLM_* 过滤，settings_from_environment，主链经 settings_from_config）；platform/runtime.py:112（DATABASE_URL 仅装配层传递）；mcp/client.py:604/619/622（credential_ref/env_refs→MCP 子进程/HTTP Bearer，缺失→McpConnectionError）+668（VENAGENT_MCP_ALLOWED_COMMANDS 默认 "node,python,python3"）；sandbox/docker.py:415（VENAGENT_SANDBOX_DISABLED→跳过 docker version 探测）；bootstrap.py:206（GITHUB_TOKEN→SkillHubService(GitHubApiClient)，可空→匿名限流）；invocation_store.py:204（VENAGENT_INVOCATION_ENCRYPTION_KEY，32B base64 AES-GCM，缺失→InvocationStoreError）。
- **MCP 凭据表单校验**：routes/control.py:66-85（env 名 `^[A-Za-z_][A-Za-z0-9_]*$`、env_refs ≤16 去重）；McpServerConfig.credential_ref/env_refs（mcp/config.py:49-50）。
- **llm 协议现状**：5 provider 工厂（openai/openai_compatible/azure_openai/anthropic/google_genai，providers.py:90-99）；chat_completions/responses 双协议（use_responses_api，providers.py:31）；reasoning_effort 仅 openai/azure（providers.py:44,62）；Anthropic thinking 走 extra_body 拆 thinking（68-76）、Gemini 走 thinking_config/budget（77-86）；EXTRA_BODY_RESERVED_KEYS（config.py:80-101）。
- **.env.example**：113 行全注释，与 ENV_FIELDS 一一对应；白名单外 4 键：NEO4J_HTTP_PORT/NEO4J_BOLT_PORT（compose 端口映射）、TEST_DATABASE_URL/TEST_NEO4J_URI（tests/conftest.py:26-63 装配，含 ${POSTGRES_PASSWORD} 占位替换+quote 编码）。
- **compose.yaml**：仅 postgres:16-alpine + neo4j:5.26.0-community 两个 infra（无 app 服务、无 config.yaml 挂载），密码 `${VAR:?}` 插值，同一 .env 供 Compose 与应用（compose.yaml:7-8 注释）；Vite dev 代理 /api+/health→8090（web/vite.config.ts:6-13），产物后端静态服务。
- **final 参考差异**：final/config/config.yaml 15 顶层键（api_url/milvus/postgres/elasticsearch/kafka 自建 infra 体系）与当前 AppConfig（llm/server/sandbox/persistence/neo4j/auth/invocation/memory_extractor/embedding）结构不同，**不能直接复用映射**；config.docker.yaml 不存在；final/docker-compose.yml 8 服务（app+7 infra）。
- **测试覆盖**：tests/test_config.py 17 用例（tmp_path 隔离+environ= 注入+monkeypatch：安全默认/覆盖顺序/类型错误不泄密/DSN quote 编码/未知 __ 键 fail-fast/extractor 继承/embedding all-or-none/invocation key）；tests/conftest.py 导入期 setdefault VENAGENT_SANDBOX_DISABLED=1+VENAGENT_INVOCATION_ENCRYPTION_KEY；test_test_configuration.py 3 用例测 conftest 装配；test_llm.py 覆盖 settings 链路（含 .env.example 无真实秘密断言）；真集成测试用 VENAGENT_RUN_DOCKER_INTEGRATION!=1 默认 skip。

## Resolution（RESOLVED，12 项拍板 + 执行设计 + 验证方案，2025-07 用户逐块确认）

### 决策（D1-D12，用户拍板）

- **D1 游离 env 点全部纳入 config.yaml**：GITHUB_TOKEN、mcp credential_ref/env_refs、VENAGENT_SANDBOX_DISABLED、VENAGENT_MCP_ALLOWED_COMMANDS、VENAGENT_INVOCATION_ENCRYPTION_KEY 全部纳入（后两者形态：sandbox.disabled 布尔 / mcp.allowed_commands 列表；invocation.encryption_key 已存在只需换来源；GITHUB_TOKEN 新增 github.token；mcp 凭据落点见阶段 3）。
- **D2 fail-fast 语义**：配置文件全量 fail-fast（未知键/类型错误→ConfigError）；进程 env 白名单放行（ENV_FIELDS 保留，含 `__` 的未知键报错维持现状）。注：q2 拍的「.env 文件全量 fail-fast」在 D8「.env 整体删除」后落点为 **config.yaml 即唯一文件配置源 → 全量 fail-fast**，二者合并后无冲突。
- **D3 单层 config.yaml**：不引入 config.local.yaml 覆盖层。
- **D4 敏感字段明文存储**：config.yaml 明文存真实 key（gitignore 保证不进 git）；SecretStr 内存/日志/接口仍不泄露。
- **D5 前端 /settings 新路由**：独立设置页面，只做 LLM 连接配置——provider / api_key / model / base_url + API 协议三选一（Anthropic | Responses | completions）+ 思考强度三档（低/中/高）。其他区块不进界面（改 yaml）。
- **D6 settings 接口**：GET /api/settings 返回非敏感字段实际值 + 敏感字段 configured 布尔（绝不回显值）；PUT /api/settings 提交后 AppConfig 全量校验 fail-fast、原子写盘（临时文件+rename，YAML 全量重写保 diff 干净）；敏感字段提交空=保持不变；owner 可读写，guest 403。
- **D7 config.example.yaml 全覆盖**：全部区块含敏感字段占位符；NEO4J_HTTP_PORT / NEO4J_BOLT_PORT / TEST_DATABASE_URL / TEST_NEO4J_URI 4 键不进 yaml（compose 与测试装配继续走 env 机制，见 D8/D11）；.env.example 删除。
- **D8 .env 整体删除**：app 不再读 .env；compose.yaml 的 `${VAR:?}` 改为 `${VAR:-默认值}`（进程 env 优先，缺省用开发默认值）；README 说明 compose 键。
- **D9 思考强度集中映射表**（后端集中，前端只传 low/medium/high 三档）：Anthropic = extended thinking + budget（低 4096 / 中 16384 / 高 32768 tokens）；OpenAI 系（chat_completions/responses）= reasoning_effort（低 minimal / 中 medium / 高 high）；completions 协议不支持 → 降级无思考（该档禁用并提示）。
- **D10 启动自举**：load_config 检测不到 config.yaml 时自动从 config.example.yaml 复制生成；敏感字段仍为空时安全默认降级（llm.provider=="" 等不启用对应能力，启动不报错，维持 test_safe_defaults 语义）。
- **D11 conftest 装配来源**：tests/conftest.py 的 _load_local_test_database_url 改从 config.yaml 的 persistence 区块（enabled+password）拼 TEST_DATABASE_URL；TEST_NEO4J_* 从 neo4j 区块；显式 TEST_* env 仍优先；config.yaml 未配置 → 对应测试 skip（维持现状语义）。
- **D12 重启生效 + 写安全**：PUT 原子写盘 + 前端提示「重启后生效」；get_runtime_config lru_cache 与装配机制零改动（不引入热重载——已向用户讲解 6 类影响面：消费时机三分/invocation key 与 JWT secret 数据绑定/run 恢复漂移/多 worker 不一致/坏文件瘫痪面/范围膨胀）；PUT 遵循写操作惯例加 require_origin。

### 执行设计（4 阶段，实现时按此展开）

**阶段 1 loader 重构（venagent/config/）**
- 拆文件：`models.py`（9 区块 _StrictModel + AppConfig 定义，含 github.token / sandbox.disabled / mcp.allowed_commands 新区块）+ `loader.py`（加载/校验/合并）。
- load_config 新语义：读 config.yaml（缺失→复制生成自 config.example.yaml）；合并顺序 安全默认 < config.yaml < 进程 env 白名单（ENV_FIELDS 保留，env > yaml）；删除 _read_dotenv 与 .env 读取。
- fail-fast：config.yaml 未知键（extra=forbid 已有）+ 类型错误 → ConfigError；进程 env 维持白名单语义（含 `__` 未知键报错）。
- llm 装配不动（providers.py 5 工厂双协议已就绪），只把 settings 链路改为接收 AppConfig 直出；思考强度映射表落 llm 层常量（三档→协议参数，D9）。

**阶段 2 settings 接口 + 前端**
- 后端：`routes/settings.py`（GET /api/settings：owner + 掩码输出 + 思考强度映射表；PUT /api/settings：owner + require_origin + AppConfig 全量校验 + 敏感空值保持 + 原子写盘），注册进 register_routes（routes/__init__.py:24-50）。
- 前端：`/settings` 路由 + SettingsPage.vue（LLM 表单：provider 下拉 / api_key（空=保持，已配置显示标记）/ model / base_url / 协议三选一 / 思考强度三档；GET 填充、PUT 保存、成功提示「重启后生效」；guest 403 引导登录）。接入 ownership store apiFetch（Bearer+401 refresh 现有封装）。
- settings 写盘范围：PUT 只允许写 LLM 区块字段（界面范围 D5），其余区块不暴露。

**阶段 3 游离点迁移（D1）**
- GITHUB_TOKEN：config.yaml 新增 `github: {token}` 区块，bootstrap.py:206 改读 config。
- mcp 凭据：`mcp: {credential_ref, env_refs, allowed_commands}` 纳入 AppConfig；mcp/client.py:604/619/622/668 与 routes/control.py:66-85 表单校验改读 AppConfig（credential_ref 语义：指向 config.yaml 内 mcp.credentials 映射的键名，缺失→沿用 McpConnectionError 语义）。
- VENAGENT_SANDBOX_DISABLED → sandbox.disabled（docker.py:415 改读 config，含 conftest 导入期 setdefault 一并改）。
- invocation.encryption_key 来源切换（invocation_store.py:204 已可注入 key 参数，改装配处传入）。
- platform/runtime.py:112 DATABASE_URL 保持「装配层传递」语义不改（bootstrap 已传 config.persistence.database_url）。

**阶段 4 compose + 测试 + 文档**
- compose.yaml：`${VAR:?}` → `${VAR:-默认值}`（POSTGRES_PASSWORD / NEO4J__USER / NEO4J_PASSWORD / NEO4J_HTTP_PORT / NEO4J_BOLT_PORT），进程 env 优先；README 说明。
- .env.example 删除（config.example.yaml 为唯一模板；4 个 compose/测试键默认值化/装配化后不再需要）。
- conftest（D11）：_load_local_test_database_url / _load_local_test_environment 改从 config.yaml 装配，显式 TEST_* env 优先，未配置 skip；导入期 setdefault 的 VENAGENT_SANDBOX_DISABLED / VENAGENT_INVOCATION_ENCRYPTION_KEY 相应调整（sandbox.disabled 走 config；invocation key 保留测试注入）。
- test_config.py 17 用例改造：YAML 用例（tmp_path 写 config.yaml + project_root 参数）+ env 覆盖优先级用例保留 + 新增 config.yaml 未知键/类型 fail-fast 用例 + 启动复制生成用例 + 敏感不泄露断言保留；test_test_configuration.py 同步改。
- 前端 Verify：Playwright（已装）浏览器级——/settings 打开、GET 掩码断言、PUT 保存成功提示、guest 403；HTTP 级——PUT 后 yaml 文件内容断言 + 重启后新 run 生效（HTTP 级验证，不重启进程的 e2e）。

### 验证方案（Resolve 标准落地）

1. .env 删除后全 config.yaml 启动：删 .env → load_config 读 config.yaml 成功（安全默认 + 已配置值），pytest 全绿。
2. 真实 key 不进 git：.gitignore 含 config.yaml；config.example.yaml 无真实 key；git status 干净。
3. 前端设置界面可用且写 config.yaml：/settings GET 掩码 + PUT 写盘 + 「重启后生效」提示。
4. env 仍可覆盖：进程 env（ENV_FIELDS 白名单）> config.yaml 优先级测试通过。
5. 启动自举：无 config.yaml 时自动复制生成（含占位符），空敏感字段安全降级启动。
6. 缺省集成测试装配：TEST_DATABASE_URL 从 config.yaml persistence 装配（显式 env 优先），未配置 skip。

### 明确不做的遗留

- 热重载 / 多 worker 广播（D12：重启生效）。
- config.local.yaml 覆盖层（D3）。
- 敏感字段加密落盘（D4：明文 + gitignore）。
- TEST_* 键进 yaml（D7）。
- 其他区块进设置界面（D5：只 LLM 连接）。