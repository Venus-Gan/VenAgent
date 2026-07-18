# Phase 1 / Sprint 01 计划：配置模型与覆盖

## 计划状态

- 状态：已完成
- 所属阶段：Phase 1：配置与 Bootstrap
- 本 Sprint 执行范围：P1-01、P1-02、P1-03
- 本 Sprint 不执行 Bootstrap、lifespan 或运行时迁移

## 阶段目标

将配置从当前 `final/config/config.py` 的加载逻辑中抽象为可验证、不可变、可脱敏的新配置边界，为后续 Bootstrap 装配提供稳定输入。

## 本 Sprint 目标

1. 定义不可变配置模型和字段级 secret 标记。
2. 实现五层配置覆盖：

   ```text
   安全默认值 → 共享 YAML → config.local.yaml → 白名单环境变量 → CLI 字段覆盖
   ```

3. 明确 mapping 深度合并、list 整体替换和标量覆盖规则。
4. 对未知字段、类型错误、非法组合和 secret redaction 建立测试门禁。
5. 保持当前 `final` 配置入口可用；不改变 HTTP、SSE、运行时和外部基础设施行为。

## 任务顺序

### P1-01：不可变配置模型

- 先阅读当前 `final/config/config.py`、配置文件、相邻测试和配置文档。
- 先写模型契约测试，覆盖字段类型、默认值、嵌套结构、只读语义和 secret 标记。
- 实现新配置模型，避免把连接对象、client、repo 或线程放进配置状态。
- 明确配置诊断输出只允许展示脱敏后的结构。

### P1-02：五层配置合并

- 先写覆盖顺序和合并行为测试。
- 实现独立的 loader/merger，不在 FastAPI、Agent 或 Infrastructure 构造器中加载配置。
- mapping 递归合并；list 整体替换；标量由高优先级来源覆盖。
- 环境变量只通过显式白名单映射进入配置，禁止任意环境变量自动注入。
- CLI 覆盖只接受已声明字段，并复用同一套类型校验。

### P1-03：失败与脱敏门禁

- 未知字段必须 fail fast，并指出字段路径。
- 类型错误必须 fail fast，不能静默转换为错误类型或空值。
- 互斥/依赖字段组合必须在模型层拒绝。
- 配置错误、启动诊断、health 输出和异常文本不得泄露 API key、token、密码或连接串中的秘密。
- 增加 secret redaction 的正向和负向测试，避免只测试固定字段名称。

## 明确不做

- 不创建 `src/venagent/bootstrap/` 的运行时装配实现；该内容属于后续 Sprint。
- 不创建 `apps/api/lifespan.py`。
- 不修改 `UnifiedAgent`、`final/main.py` 的启动路径。
- 不添加 LangGraph、MCP、checkpoint 或其他新生产依赖。
- 不启动 Docker Compose，不访问真实 LLM、数据库、MCP 或外部网络。
- 不提交、推送、创建 PR 或重写 Git 历史。
- 不顺手修复 Phase 0 遗留缺陷（P0-11 至 P0-15）。

## 预计涉及文件

### 新增

- `src/venagent/infrastructure/config/` 下的配置模型、loader、merger 和 redaction 模块。
- `final/tests/` 下与配置契约对应的测试。

### 可能更新

- `final/config/config.py`：仅在需要建立兼容 façade 时最小修改。
- 配置文档：仅补充已实现且经过测试的规则。

### 禁止反向依赖

- `src/venagent/**` 不得导入 `final/**`。
- 新配置模块不得依赖 FastAPI、UnifiedAgent、具体 Infrastructure client 或外部服务。

## TDD 与审查流程

每个子任务按以下顺序执行：

1. 写测试并确认 RED；
2. 写最小实现并确认 GREEN；
3. 重构并重新运行相关测试；
4. 执行通用 Python/代码质量审查；
5. 运行完整测试、compileall、覆盖率和安全检查；
6. 更新 `tdd-report.md`、`review.md` 和任务状态。

如果测试暴露出当前 legacy 配置行为与目标规则冲突，先记录兼容决策并暂停，不自动扩大范围。

## 验收门禁

- [x] P1-01 模型契约测试通过，配置对象不可变。
- [x] P1-02 五层覆盖顺序和合并规则测试通过。
- [x] P1-03 未知字段、类型错误、非法组合和 secret redaction 测试通过。
- [x] `src/venagent/**` 不导入 `final/**`。
- [x] 不影响现有 `final` 测试和 HTTP/SSE characterization 基线。
- [x] 不增加未经批准的生产依赖。
- [x] `python -m compileall -q final src` 通过。
- [x] 完整 pytest 通过，网络熔断保持 ENABLED。
- [x] 重构关键配置路径覆盖率达到 94%；整体 legacy 覆盖率仍按 Phase 0 记录为 59%。
- [x] 本 Sprint 新增配置代码的专项审查未发现 CRITICAL/HIGH；legacy DSN 日志和旧入口未接入风险记录于 `review.md`，不伪造为已解决。

## 暂停点

完成 P1-01 后暂停一次，确认配置模型字段和兼容策略；完成 P1-03 后暂停一次，确认是否进入下一个 Sprint 的 Bootstrap。

## 后续 Sprint 顺序

| Sprint | 范围 | 前置条件 |
|---|---|---|
| Sprint 01 | P1-01～P1-03：配置模型、合并、校验 | 本计划审批 |
| Sprint 02 | P1-04～P1-05：新目录骨架、dependency container、Bootstrapper | Sprint 01 验收 |
| Sprint 03 | P1-06～P1-08：Bootstrap 阶段迁移、lifespan、health/degradation | Sprint 02 验收 |
| Sprint 04 | P1-09～P1-10：兼容 façade、启动/关闭/降级集成门禁 | Sprint 03 验收 |
