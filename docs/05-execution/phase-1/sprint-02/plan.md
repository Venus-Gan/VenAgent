# VenAgent Phase 1 / Sprint 02 计划

## 计划状态

- 状态：已完成
- 所属阶段：Phase 1：配置与 Bootstrap
- 本 Sprint 范围：P1-04、P1-05
- 前置条件：Sprint 01（P1-01～P1-03）已验收
- 实施原则：先测试、后实现；只建立可测试的骨架和阶段契约，不提前迁移旧运行时

## Sprint 目标

在不改变当前 `final/` 运行行为的前提下，建立新的组合根边界：

1. 创建 `apps/api` 与 `src/venagent/bootstrap` 的最小目录骨架。
2. 建立显式、可注入、可测试的 dependency container。
3. 提取 staged Bootstrapper 的阶段模型、结果模型和错误诊断契约。
4. 为 Sprint 03 的真实资源初始化、FastAPI lifespan 和 capability health 预留明确接口。
5. 保持新代码不反向导入 `final`，不访问真实 LLM、数据库、MCP 或网络。

## 任务拆分

### P1-04：目录骨架与 dependency container

计划新增：

- `apps/__init__.py`
- `apps/api/__init__.py`
- `apps/api/main.py`：新入口的最小应用工厂边界；本 Sprint 不注册旧 Handler 路由
- `src/venagent/bootstrap/__init__.py`
- `src/venagent/bootstrap/container.py`：显式依赖容器和工厂类型
- 必要的 `src/venagent` 包初始化文件

设计约束：

- container 保存配置和显式 factory/provider，不提供隐式 service locator。
- container 不创建网络 client、数据库连接、线程、worker 或 Agent 实例。
- container 使用不可变或只读边界；构造后不允许通过共享可变字典偷偷注入依赖。
- `apps/api` 只依赖新包的 bootstrap/application 边界，不直接导入 `final/internal`。
- `src/venagent/**` 不得出现 `from final` 或 `import final`。
- 不新增生产依赖；复用 Sprint 01 已存在的 Pydantic/PyYAML/FastAPI 依赖。

### P1-05：staged Bootstrapper

计划新增：

- `src/venagent/bootstrap/stages.py`：阶段标识、阶段状态和阶段诊断 DTO
- `src/venagent/bootstrap/bootstrapper.py`：按固定顺序执行显式 factory 的 Bootstrapper
- `final/tests/test_phase1_bootstrap.py`：契约、顺序、失败归因和边界测试

本 Sprint 只实现装配框架，不实现旧资源迁移。阶段模型先覆盖：

1. `config`：接收已完成校验的 `VenAgentConfig`；不在 Bootstrapper 中重复定义配置规则。
2. `infrastructure`：仅调用注入的 provider；测试使用 fake provider。
3. `application`：仅验证依赖装配可以继续传递；不迁移 `UnifiedAgent`。
4. `app`：返回新入口所需的最小装配结果；不挂载 legacy Handler。

每个阶段必须产生结构化状态，失败时至少包含阶段名、稳定错误类别和安全诊断文本；不得把 secret、完整 DSN 或异常中的凭据直接写入结果或日志。资源健康/降级语义、反序关闭和并发初始化留给 Sprint 03/04。

## 明确不做

- 不修改 `final/main.py` 的实际启动路径，不替换 `APIConfig`，不实现 `build_deps` façade。
- 不迁移 `UnifiedAgent.__init__` 或 `_bootstrap_concurrent`；对应 P1-06。
- 不创建或接入 `apps/api/lifespan.py`；对应 P1-07。
- 不实现 capability health、durable/non-durable 降级模型；对应 P1-08。
- 不实现旧入口兼容 façade 和完整启动/关闭集成测试；对应 P1-09/P1-10。
- 不注册现有 HTTP/SSE 路由，不改变 OpenAPI、SSE 或前端行为。
- 不启动 Docker Compose，不访问真实 LLM、数据库、MCP 或外部网络。
- 不新增依赖，不修改配置秘密，不创建 `.env` 或写入真实凭据。
- 不顺手修复 Phase 0 遗留问题，不提交、推送或创建 PR。

## TDD 执行顺序

### RED

先新增测试并确认失败，至少覆盖：

- 新包和 `apps.api` 的导入边界。
- container 能接收 fake provider，并拒绝隐式依赖缺失。
- Bootstrapper 按声明顺序执行阶段，阶段结果可观察。
- 任一阶段失败时，错误归因到正确阶段，后续阶段不执行。
- 失败诊断和 `repr` 不泄露 sentinel secret、密码或 DSN。
- 新代码静态检查不导入 `final`。

### GREEN

以最小实现满足上述契约：

- 先实现类型和不可变容器，再实现阶段执行器。
- provider/factory 由测试注入，默认不触发任何外部副作用。
- `apps/api/main.py` 只提供可测试的工厂入口，不承担旧应用迁移。

### REFACTOR

- 收紧命名、类型边界和错误模型。
- 删除重复的装配逻辑，保持组合根集中在 bootstrap。
- 补充 docstring 与后续 Sprint 的接入注释，但不复制旧实现。

## 计划涉及文件

### 新增

- `apps/__init__.py`
- `apps/api/__init__.py`
- `apps/api/main.py`
- `src/venagent/bootstrap/__init__.py`
- `src/venagent/bootstrap/container.py`
- `src/venagent/bootstrap/stages.py`
- `src/venagent/bootstrap/bootstrapper.py`
- `final/tests/test_phase1_bootstrap.py`

### 不应修改

- `final/main.py`、`final/internal/**` 的运行逻辑
- `final/config/config.py` 与已验收的 Sprint 01 配置模型，除非测试证明存在必要的边界修正
- HTTP/SSE characterization fixtures 和网络熔断器

## 验证与审查门禁

实现完成后依次执行：

1. Sprint 02 定向测试，确认 RED→GREEN→REFACTOR 记录完整。
2. `cd final && python -m pytest tests`，确认现有测试全绿。
3. 新 bootstrap 代码覆盖率达到 80% 以上。
4. `python -m compileall -q final src apps`。
5. 静态确认 `src/venagent/**` 不导入 `final/**`。
6. `git diff --check`。
7. 运行 Python/通用代码审查和安全审查，重点检查依赖容器、异常诊断、secret redaction 和副作用边界。
8. 网络熔断保持 ENABLED；不进行真实 LLM 或基础设施测试。

## 验收标准

- [x] P1-04 的新目录骨架可导入、可测试，且不反向依赖 `final`。
- [x] dependency container 的依赖来源显式，fake provider 可替换，构造无外部副作用。
- [x] P1-05 的 Bootstrapper 阶段顺序固定且可观测。
- [x] 阶段失败包含安全、稳定的阶段诊断，后续阶段不会误执行。
- [x] 未提前实现 P1-06～P1-10 的运行时迁移内容。
- [x] 定向测试、完整测试、语法检查和覆盖率门禁通过。
- [x] Python、通用代码和安全审查无 CRITICAL/HIGH 新问题。
- [x] 已更新 `tdd-report.md`、`review.md` 和任务状态；等待 Sprint 03 单独审批。

## 实施结果

- 新增 `apps/api` 最小入口；入口只在显式调用 `create_app` 时执行装配，并能从仓库根目录导入。
- 新增不可变 `DependencyContainer`、`BootstrapDependencies`、阶段诊断 DTO 和 `StagedBootstrapper`。
- 同步 Bootstrapper 拒绝 awaitable factory；阶段失败按已创建依赖反序清理；取消/中断先清理再原样传播；异步 `close()` 在同步边界被安全记录为 cleanup failure。
- 未修改 `final/main.py`、`final/internal/**`、HTTP/SSE/OpenAPI 运行路径，未访问真实外部服务。

## 交付物

- 本计划审批后才开始代码实现。
- 实施完成后补充：
  - `docs/05-execution/phase-1/sprint-02/tdd-report.md`
  - `docs/05-execution/phase-1/sprint-02/review.md`
  - Sprint 02 实际变更与遗留风险说明

## 暂停点

- Sprint 02 已通过全部门禁，当前暂停，不自动进入 Sprint 03。
- Sprint 03 仍需单独生成计划并取得用户审批。
