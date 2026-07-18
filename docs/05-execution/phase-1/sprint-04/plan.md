# VenAgent Phase 1 / Sprint 04 计划

## 计划状态

- 状态：已完成
- 所属阶段：Phase 1：配置与 Bootstrap
- 本 Sprint 范围：P1-09、P1-10
- 前置条件：Sprint 03（P1-06～P1-08）已收口
- 用户已批准执行，Phase 1 最后一项环境注入收口已完成

## 前置收口证据

Sprint 03 延迟专项审查问题已完成修复和复核：

- 全量测试：295 passed；
- `src/venagent` 覆盖率：94%；
- `compileall`、AST 反向依赖检查和 `git diff --check` 通过；
- 测试网络熔断保持开启，并覆盖 requests 与 socket 层；
- app factory 已延迟资源装配到 lifespan，生命周期失败诊断、worker 排空和旧入口局部回滚已补齐。

## Sprint 目标

在不改变 HTTP/SSE/OpenAPI 外部契约的前提下，让旧入口可以单向委托新 Bootstrap/lifespan 边界：

1. 保留 `APIConfig`、`build_deps()`、`Deps` 和现有 Handler 的兼容调用形状；
2. 将旧入口的配置、资源创建、runtime 初始化和 app 装配接到显式依赖容器；
3. 用集成测试证明启动、失败、取消、关闭和 capability degradation 没有资源泄漏或虚假成功；
4. 为后续 Phase 2 保留清晰的回滚点，不提前迁移 CapabilityBroker、授权、真实 LangGraph、MCP 或真流式链路。

## P1-09：APIConfig/build_deps 兼容 façade

### 设计约束

- `final/` 只能作为兼容入口单向调用 `apps/` 和 `src/venagent`；新代码不得导入 `final`。
- `APIConfig` 的旧字段和默认入口保持兼容，配置转换必须显式、可测试、失败即停，不静默回退到不完整默认值。
- `build_deps()` 的旧返回字段 `cfg`、`inf`、`agent`、`app` 保持可用；装配中任一阶段失败必须关闭已经创建的资源。
- `create_app()` 保持无副作用 factory 语义；资源只在 lifespan startup 创建和注册。
- app state 只保存安全诊断、生命周期状态或 health DTO，不保存配置 secret、Infrastructure、Agent、连接、锁或线程。

### 计划变更

- 在 `apps/api/` 增加或调整兼容适配层，把 legacy config/handler 需要的对象映射到新依赖容器；不把 legacy 业务逻辑复制到新包。
- 修改 `final/main.py`，使 `build_deps()` 和 `main()` 只承担兼容委托、旧调用形状和关闭兜底。
- 保留 `final/internal/handler/handler.py` 的路由、SSE envelope 和 OpenAPI 形状；不在本 Sprint 重写 Handler。
- 为配置转换、build facade、懒 app factory、局部回滚和异常脱敏增加单元/集成测试。

## P1-10：启动/关闭/降级集成门禁

### 必须覆盖的场景

1. 旧入口正常启动：配置→Infrastructure→Agent/runtime→路由装配顺序可观察；
2. Infrastructure、Agent runtime、路由装配任一阶段失败时，已创建资源按反序关闭；
3. lifespan 正常退出、关闭失败、取消和重复 shutdown 均不遗留 worker 或后台线程；
4. PostgreSQL 不可用时 chat/短期记忆保持可用，durable workflow 明确拒绝；
5. Milvus 或 Elasticsearch 单独不可用时 RAG 标记 unavailable，不伪报 degraded 可用；
6. Kafka、Neo4j、sandbox、LLM 的已有 health/degradation 语义保持局部影响；
7. HTTP/SSE/OpenAPI 与 Phase 0 characterization 基线无未批准差异；
8. 测试期间网络熔断为 ENABLED，不连接真实 LLM、HTTP、数据库、MCP 或 Docker。

## TDD 执行顺序

### RED

- 先补 `APIConfig/build_deps` 兼容形状和旧入口委托测试；
- 先补真实 app factory 不创建资源的 lifespan 集成测试；
- 先补 startup/route/runtime/close 失败回滚测试；
- 先补 capability degradation 与 HTTP/SSE/OpenAPI characterization 回归；
- 运行定向测试，确认新门禁在实现前真实失败。

### GREEN

1. 实现最小 config-to-container 兼容映射；
2. 实现旧 `build_deps()` façade 和局部回滚；
3. 将旧入口接入新 lifespan，但保留旧返回字段和路由外形；
4. 完成启动/关闭/降级集成门禁。

### REFACTOR

- 删除重复的资源装配分支和隐式全局状态；
- 收紧兼容 façade 的类型和错误边界；
- 确认所有诊断只包含稳定阶段、reason code 和安全摘要；
- 做 Python、FastAPI、并发、代码规范和安全复核；
- 不把本 Sprint 的兼容 façade 当成最终架构，后续仍由 Phase 2 Ports/授权继续收敛。

## 计划涉及文件

### 重点修改

- `apps/api/main.py`
- `apps/api/lifespan.py`
- `final/main.py`
- `final/config/config.py`（仅限兼容映射和失败语义）
- `src/venagent/bootstrap/`（仅限 façade 所需的显式接口）

### 测试与文档

- 新增 `final/tests/test_phase1_compat.py`；
- 新增或扩展 `final/tests/test_phase1_integration.py`；
- 扩展 HTTP/SSE/OpenAPI characterization 回归测试；
- 新增 `docs/05-execution/phase-1/sprint-04/tdd-report.md` 和 `review.md`；
- 更新 Phase 1 任务状态和路线图，但只在门禁通过后标记 P1-09/P1-10 完成。

## 明确不在本 Sprint

- 真流式 LLM→RuntimeEvent→SSE 实现；
- 新 HTTP/SSE 路由、API envelope 或 OpenAPI 契约设计；
- 真实 PostgreSQL、Milvus、Elasticsearch、Kafka、Neo4j、Docker、MCP 或 LLM 测试；
- LangGraph、CapabilityCatalog、CapabilityBroker、授权交集和 AgentTeam 重构；
- 添加依赖、启动 Compose、提交、推送或创建 PR。

## 验证门禁

1. P1-09/P1-10 定向测试通过，并记录 RED→GREEN→REFACTOR；
2. `cd final && python -m pytest tests` 全量通过；
3. 关键新代码和项目整体覆盖率不低于 80%；
4. `python -m compileall -q final src apps` 通过；
5. AST 确认 `src/venagent/**`、`apps/**` 不导入 `final/**`；
6. `git diff --check` 通过；
7. 网络熔断保持 ENABLED；
8. 完成 Python、FastAPI、通用代码规范、并发和安全审查；
9. 所有 CRITICAL/HIGH 问题解决后，才允许将 P1-09/P1-10 标记为完成。

## 实施结果

- 新增 `apps/api/compat.py`，完成 legacy `APIConfig` 到不可变 `AppConfig` 的显式映射。
- `final/main.py` 的 `build_deps()` 已通过兼容 façade 委托新 `StagedBootstrapper`，保留 `Deps` 字段和旧 Handler 调用形状。
- legacy 配置显式路径和 `AGI_CONFIG` 路径读取失败时 fail-fast，不再静默回退到默认配置。
- 补齐旧入口、懒 app factory、startup/runtime/route 失败回滚、关闭、取消、health degradation 和网络熔断集成门禁。
- 未修改 HTTP/SSE/OpenAPI 外部契约，未添加依赖，未启动真实外部服务。

## Phase 1 最后收口：`.env` 环境变量注入

P1-09 原有兼容映射已完成，但此前只验证了直接传入 `environ` 的配置契约，未贯通 `.env → 环境变量 → legacy main.py`。本收口项补齐：

- 新增显式 `.env` 文件加载；`.env` 值作为环境层，进程环境变量优先级更高；
- 仅允许 `ENV_FIELD_MAP` 白名单变量进入配置，未知变量忽略；
- legacy `final/main.py` 改用 canonical loader，再转换为旧 `APIConfig`；
- 提供不含真实凭据的 `.env.example`，真实 `.env` 保持 ignored；
- 增加 `.env` 优先级、类型解析、legacy 入口和 secret 脱敏测试；
- 完成后将新增任务 P1-11 标记为 DONE，Phase 1 才正式收口。

### 收口结果

- canonical loader 支持显式 `.env` 文件；进程环境变量覆盖 `.env`，`.env` 覆盖 YAML；
- `final/main.py` 通过 canonical loader 和 compat 转换读取 `.env`，旧 `APIConfig` 实际获得环境变量值；
- 新增根目录 `.env.example`，真实 `.env` 未创建、保持 ignored；
- 新增 `.env` 解析、优先级、legacy 入口和 secret 脱敏回归测试。

## 暂停点

Sprint 04 及 Phase 1 最后 `.env` 注入收口均已通过门禁。当前暂停，不自动进入 Phase 2；后续任务需要单独生成计划并取得用户审批。
