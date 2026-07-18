# Sprint 04 TDD 报告

## 范围

- P1-09：`APIConfig/build_deps` 兼容 façade；
- P1-10：旧入口启动、关闭和 capability degradation 集成门禁。

## RED

- 新增兼容与集成测试后，定向测试首次结果为 5 failed、3 passed；失败集中在兼容模块缺失和 legacy 配置读取错误静默回退。
- 失败测试覆盖：legacy→AppConfig 映射、StagedBootstrapper 委托、部分 Agent 回滚、配置 fail-fast、旧入口 façade 和 app shell 状态隔离。

## GREEN

- 新增 `apps/api/compat.py`，完成显式配置映射和 legacy factory 注入；runtime 初始化失败会关闭部分创建的 Agent，后续 Bootstrap cleanup 关闭 Infrastructure。
- `final/main.py` 通过兼容 façade 委托新 `StagedBootstrapper`，保持 `Deps(cfg, inf, agent, app)` 和 Handler 调用形状。
- legacy 显式配置路径和 `AGI_CONFIG` 路径读取失败改为安全 fail-fast。
- P1-09/P1-10 定向测试：15 passed；P1-11 `.env` 收口定向测试：14 passed；全量测试：309 passed。

## REFACTOR

- 新架构代码不导入 `final`；legacy 仅从旧入口单向注入工厂。
- 配置 secret 只进入 Pydantic `SecretStr`，兼容错误不回显原始配置值。
- app shell 只接收 router/middleware 元数据，不复制 built app 的 runtime state。
- 保留真流式、LangGraph、MCP、真实外部设施和新 API 契约在本 Sprint 之外。
- canonical loader 使用 `.env` 作为环境层，进程环境变量覆盖 `.env`，legacy `main.py` 通过 compat 映射实际消费结果。

## 验证结果

```text
cd final && python -m pytest tests --cov=../src/venagent --cov=../apps/api --cov-report=term-missing
309 passed
src/venagent 覆盖率：93%
apps/api 覆盖率：90%

python -m compileall -q final src apps
通过

AST 反向导入检查
通过，无 src/venagent 或 apps 导入 final

git diff --check
通过（仅既有 LF/CRLF 提示）
```

测试网络熔断保持 ENABLED；未连接真实 LLM、HTTP、数据库、MCP 或 Docker。
