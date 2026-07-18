# VenAgent Phase 1 / Sprint 03 计划

## 计划状态

- 状态：已完成
- 所属阶段：Phase 1：配置与 Bootstrap
- 本 Sprint 范围：P1-06、P1-07、P1-08
- 前置条件：Sprint 02（P1-04、P1-05）已验收
- 后续 Sprint：Sprint 04 执行 P1-09、P1-10
- 实施原则：先测试、后实现；先建立生命周期和健康契约，再接入兼容入口

## Sprint 目标

将旧 Agent 构造器中的启动副作用迁移到 Bootstrap/lifespan 边界，并建立可诊断的 capability health 与降级模型：

1. 将 `_bootstrap_concurrent()` 的四路并发编排移出 `UnifiedAgent`，保留现有恢复、RAG 索引和 sandbox 初始化行为。
2. 建立 FastAPI lifespan 的异步启动/反序关闭边界，支持同步资源和异步资源的统一清理。
3. 建立不依赖真实 PostgreSQL、Milvus、Elasticsearch、Kafka、Neo4j 或 LLM 的 health/degradation 契约。
4. 明确 PostgreSQL 不可用时 chat 的 non-durable 降级和 durable workflow 的拒绝语义。
5. 保持现有 HTTP/SSE/OpenAPI、前端、旧 `final/main.py` 调用形状和网络熔断测试环境不变。

## 任务拆分

### P1-06：迁移 `_bootstrap_concurrent`

#### 设计

把“并发执行和等待”的通用逻辑放入目标 Bootstrap 层，把旧模块的四个初始化动作保留为兼容适配器提供的 callback：

1. `ragchunk.init(dim)`；
2. `restore_from_db(agent)`；
3. `restore_rag_from_db(agent)`；
4. `init_sandbox(agent)`。

并发编排必须满足：

- 四个独立任务可以并发执行；
- 单个任务失败只影响对应 capability，不阻塞其他任务；
- 所有任务完成后，依赖恢复结果的知识图谱初始化仍保持串行后置；
- 线程必须可观察、可等待、可回收，不留下未完成 daemon worker；
- 错误诊断只暴露稳定阶段/任务标识和安全错误类别，不保留原始异常对象或敏感上下文；
- 取消/中断时等待或停止策略必须明确，不能静默遗留后台线程。

#### 计划变更

- 新增 `src/venagent/bootstrap/concurrent.py`：通用并发初始化编排、任务结果和安全诊断。
- 新增 `final/internal/agent/bootstrap_adapter.py`：只负责把现有四个 legacy 初始化函数绑定到新编排器；不新增业务逻辑。
- 修改 `final/internal/agent/agent.py`：删除 `_bootstrap_concurrent()` 内的线程实现和构造器直接启动；改为显式 runtime initialization hook。
- 必要时最小修改 `final/main.py`：在既有 `build_deps()` 调用链中显式调用 runtime initializer；只补启动调用，不提前实现 P1-09 的 `APIConfig/build_deps` façade，也不改变 HTTP/SSE 路由。
- 保留旧测试的行为断言，但将测试主体转向 Bootstrap 编排器；兼容适配器仅验证 callback 绑定和旧行为未改变。

#### 构造器副作用门禁

`UnifiedAgent.__init__()` 不得再执行以下操作：

- 创建线程或等待启动线程；
- 调用 `restore_from_db`、`restore_rag_from_db` 或 `init_sandbox`；
- 执行知识图谱恢复；
- 将持久化恢复结果写入内存状态。

这些操作由显式 runtime initializer 在 lifespan/bootstrap 阶段执行。Sprint 03 不重写 RAG、memory、document 或 sandbox 底层实现。

### P1-07：FastAPI lifespan 装配与关闭

#### 设计

使用异步上下文管理器作为应用生命周期唯一入口：

- startup 按 Bootstrap 阶段顺序创建资源并记录已创建资源；
- 独立初始化任务可使用受控并发，但不在 Agent 构造器中启动；
- shutdown 严格按照成功创建顺序反序执行；
- 同步 `close()` 在异步边界通过明确的同步调用策略执行；
- 异步 `close()` 必须被 await；
- 某个资源关闭失败时继续关闭其他资源，最终返回安全的 cleanup diagnostics；
- startup 失败时清理已创建资源，并重新抛出稳定的 Bootstrap 错误；
- 应用状态只保存已装配的依赖容器/生命周期结果，不把连接、线程、锁或 secret 放入业务 state。

#### 计划变更

- 新增 `src/venagent/infrastructure/lifecycle/__init__.py`。
- 新增 `src/venagent/infrastructure/lifecycle/manager.py`：资源注册、startup/shutdown、反序清理和失败诊断。
- 新增 `apps/api/lifespan.py`：FastAPI `lifespan` 适配器，连接 `DependencyContainer` 与生命周期管理器。
- 修改 `apps/api/main.py`：在显式 `create_app()` 调用时注入 lifespan；导入期间不创建资源。
- 必要时补充 `src/venagent/bootstrap/bootstrapper.py` 的异步入口，但不破坏 Sprint 02 已有同步边界。

#### 兼容边界

- Sprint 03 不把 `final/main.py` 改造成完整的 `APIConfig/build_deps` façade；该工作属于 P1-09。
- Sprint 03 不注册新的 HTTP/SSE 路由，也不切换生产默认入口。
- Sprint 03 的 lifespan 先以显式 factory 和 fake resource 完成契约测试；旧入口的全面启动/关闭集成门禁放在 P1-10。

### P1-08：capability health 与降级模型

#### 设计

在 `src/venagent/infrastructure/health/` 建立框架无关的健康模型，不直接复用 legacy `Status` 字符串：

- capability 标识和依赖标识；
- `available`、`degraded`、`unavailable`、`disabled` 等稳定状态；
- 是否支持 non-durable 使用；
- 是否支持 durable/recovery 使用；
- 安全的 reason code 和可选诊断摘要；
- health snapshot 的不可变表示。

最低降级规则：

| 故障能力 | 仍可用能力 | 明确拒绝或降级 |
|---|---|---|
| PostgreSQL | 无持久化 chat、无依赖 PG 的本地能力 | durable workflow、跨重启恢复 |
| Milvus/Elasticsearch | 普通 chat、文档基础操作（若其自身可用） | 对应 RAG 检索/索引能力标记 unavailable |
| Kafka | 不依赖事件发布的请求 | 事件发布标记 degraded，不得伪报成功 |
| Neo4j | 非图模式 memory/RAG | 图增强能力标记 degraded |
| sandbox/Docker | chat、只读能力 | exec_command 能力不注册或明确拒绝 |
| LLM | 本地健康/status 查询 | 需要模型生成的请求明确失败，不伪造答案 |

健康模型只负责“能力是否可用及降级决策输入”，不在本 Sprint 实现 Phase 2 的 CapabilityCatalog、CapabilityBroker、授权交集或 MCP adapter。

#### 计划变更

- 新增 `src/venagent/infrastructure/health/models.py`：不可变 health/degradation DTO、枚举和稳定 reason code。
- 新增 `src/venagent/infrastructure/health/evaluator.py`：从 fake/注入的基础设施状态生成 capability health snapshot。
- 新增 `src/venagent/infrastructure/health/__init__.py`：受控导出。
- 不修改 legacy `/health` 外部 envelope；新模型先作为 bootstrap/application 内部状态和后续兼容 façade 的数据源。

## TDD 执行顺序

### RED

先新增或改写测试，并确认以下失败：

- 并发编排按任务集合执行，四路任务确实重叠运行；
- 任一任务失败不阻塞其他任务，失败诊断不泄露原始异常文本；
- `UnifiedAgent.__init__()` 不调用恢复、sandbox、KG 或线程启动路径；
- 显式 runtime initializer 能在构造完成后执行这些操作；
- lifespan startup/yield/shutdown 的顺序可观察；
- startup 失败能反序清理已经创建的资源；
- shutdown 同时支持同步 `close()`、异步 `close()`，且一个关闭失败不阻塞其余资源；
- health snapshot 对相同输入稳定、不可变，并能区分可用、降级、不可用和禁用；
- PostgreSQL 不可用时 non-durable chat 可用，durable workflow 不会被错误标记为可恢复；
- 无任何真实外部设施时，健康评估和生命周期测试仍可完整运行。

### GREEN

以最小实现满足测试：

1. 先实现通用并发任务结果和安全错误 DTO；
2. 再把 legacy callback 接入新编排器并移除 Agent 内部线程实现；
3. 实现生命周期管理器和 FastAPI lifespan 适配；
4. 实现 health/degradation evaluator；
5. 最后把 bootstrap 结果与 app state 连接起来。

### REFACTOR

- 收紧资源注册和关闭接口的类型边界；
- 确保 cleanup 失败不会覆盖 startup 原始失败；
- 删除重复的 legacy status 映射和隐式全局状态；
- 保证健康模型与 Sprint 02 的阶段诊断解耦；
- 检查新代码不导入 `final`，兼容适配器只能由旧目录单向调用新包。

## 计划涉及文件

### 新增

- `src/venagent/bootstrap/concurrent.py`
- `src/venagent/infrastructure/lifecycle/__init__.py`
- `src/venagent/infrastructure/lifecycle/manager.py`
- `src/venagent/infrastructure/health/__init__.py`
- `src/venagent/infrastructure/health/models.py`
- `src/venagent/infrastructure/health/evaluator.py`
- `apps/api/lifespan.py`
- `final/internal/agent/bootstrap_adapter.py`
- `final/tests/test_phase1_lifecycle.py`
- `final/tests/test_phase1_health.py`

### 修改

- `src/venagent/bootstrap/__init__.py`
- `src/venagent/bootstrap/bootstrapper.py`
- `apps/api/main.py`
- `final/internal/agent/agent.py`
- `final/internal/agent/memory_writer.py`
- `final/internal/memory/preference.py`
- `final/internal/rag/rag.py`
- `final/main.py`（仅限旧入口显式调用 runtime initializer）
- `final/tests/test_bootstrap_concurrent.py`
- `final/tests/test_phase1_concurrent.py`
- `final/tests/test_phase1_bootstrap.py`
- 必要时更新 `final/tests/test_phase1_bootstrap.py` 的生命周期契约断言

### 明确不修改

- `final/main.py` 的完整兼容 façade 和 `build_deps()` 迁移逻辑（P1-09）；
- P1-10 的旧入口启动/关闭/降级集成门禁；
- `final/internal/handler/handler.py` 的路由、SSE envelope 和 OpenAPI 契约；
- `final/internal/infra/infra.py` 的底层连接算法和数据库 schema；
- `final/requirements.txt`、LangGraph/MCP 依赖；
- 真流式 LLM→RuntimeEvent→SSE 链路；
- Phase 0 遗留缺陷、真实 LLM、真实数据库、Docker Compose 和外部网络。

## 验证与审查门禁

实施完成后按以下顺序验证：

1. P1-06～P1-08 定向测试，完整记录 RED→GREEN→REFACTOR；
2. `cd final && python -m pytest tests`，确认现有回归测试全绿；
3. `python -m compileall -q final src apps`；
4. 新 bootstrap/lifecycle/health 代码覆盖率达到 80% 以上，项目整体不低于既有基线；
5. AST/静态检查确认新 `src/venagent/**` 不导入 `final/**`；
6. `git diff --check`；
7. 验证网络熔断仍为 ENABLED，测试不发起真实 HTTP/socket/LLM 请求；
8. 进行通用代码、Python 并发、FastAPI lifespan 和安全审查；
9. 所有 CRITICAL/HIGH 问题在 Sprint 关闭前解决；
10. 更新 Sprint 03 的 `tdd-report.md`、`review.md`，并只更新 P1-06～P1-08 状态。

## 验收标准

- [x] `_bootstrap_concurrent` 的并发编排已从 `UnifiedAgent` 移出，四路初始化行为和失败隔离保持兼容。
- [x] `UnifiedAgent.__init__()` 不创建线程、不执行恢复、不执行 KG/sandbox 启动副作用。
- [x] 显式 runtime initializer/lifespan 承担启动期初始化，且失败可诊断。
- [x] FastAPI lifespan 可启动、yield、反序关闭；同步/异步资源均有测试。
- [x] startup 失败和 cleanup 失败均不会泄露 secret、原始异常上下文或未关闭 worker。
- [x] capability health snapshot 不依赖真实外部服务，状态和降级 reason 稳定、可测试。
- [x] PostgreSQL 不可用时不会错误承诺 durable workflow 恢复；无关 chat 能力仍可用。
- [x] 未改变 HTTP/SSE/OpenAPI、前端行为、网络熔断配置和生产依赖。
- [x] 定向测试、完整测试、语法、覆盖率和适用审查全部通过。
- [x] P1-09、P1-10 未被提前标记为完成；Sprint 04 仍需单独计划和审批。

## 风险与回滚

| 风险 | 控制 | 回滚方式 |
|---|---|---|
| Agent 构造副作用移除后旧调用缺少显式初始化 | 保留兼容 adapter 和定向构造测试；不提前删除旧入口 | 恢复旧入口 adapter，不切换新默认入口 |
| 同步线程与异步 lifespan 混用导致死锁或遗留 worker | 只允许 Bootstrap 管理线程；测试 join、取消和关闭 | 关闭并发初始化 feature path，保留同步 fake 初始化 |
| 资源关闭失败遮蔽启动错误 | 分离 primary error 与 cleanup diagnostics | 回退到 Sprint 02 的安全同步关闭边界 |
| 健康状态与后续 CapabilityBroker 语义不一致 | 本 Sprint 只冻结最小状态/降级契约，不实现授权 | 通过版本化 health DTO 做兼容映射 |
| legacy status/API 发生外部契约漂移 | 不修改 `/health` envelope，执行 Phase 0 characterization 回归 | 仅回退内部 health evaluator |

## 实施结果

- 新增通用并发 Bootstrap 编排器和 legacy Agent runtime adapter；旧 `_bootstrap_concurrent` 仅保留无状态兼容包装。
- `UnifiedAgent` 构造器不再执行恢复、RAG 已有数据检查、KG 初始化或 memory writer worker 启动；由显式 `initialize_runtime()` 和 lifespan 管理。
- 新增同步/异步资源生命周期管理器；同步 hook 在线程中执行，取消时先等待线程完成，关闭按创建顺序反序进行，失败继续清理并保持安全诊断。
- FastAPI app factory 只创建无副作用 app shell，资源装配延迟到 lifespan startup；app state 只保存安全诊断和生命周期状态。
- memory writer stop 先排空待处理任务，再等待 worker 退出；旧 runtime initializer 和 `build_deps()` 均具备失败回滚。
- 新增 capability health/degradation 模型；PostgreSQL 不可用时 durable workflow 标记不可用，chat 等无关能力不被连带阻塞。
- 未修改 HTTP/SSE/OpenAPI 外部契约，未添加依赖，网络熔断保持开启。

## 暂停点

Sprint 03 已完成并验收。当前暂停，不自动进入 Sprint 04；P1-09/P1-10 需要单独生成计划并取得用户审批。
