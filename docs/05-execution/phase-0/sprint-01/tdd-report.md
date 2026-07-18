# Phase 0 / Sprint 01 TDD 报告

## 本轮测试目标

为 tracked 配置和 Compose 凭据注入建立回归保护，确保：

- tracked `config.yaml` 不包含服务密码；
- Compose 的服务凭据必须由外部环境或 ignored `.env` 注入；
- local secret 配置路径仍被 Git 忽略。

## 测试资产

已新增：`final/tests/test_phase0_security_baseline.py`

## Red / Green 状态

- 预期 Red：在清理配置前，这些断言会发现 tracked 默认密码和 Compose 硬编码凭据。
- 当前实现：已清理配置并补充外部变量注入。
- Green 验证：`python -m pytest tests/test_phase0_security_baseline.py -q` 通过，3 passed。
- pytest 全局网络熔断测试通过，4 passed；默认阻止真实 `requests` 外连。
- HTTP/SSE/OpenAPI characterization 定向测试通过，12 passed。

## 其他验证

- `python -m pytest tests --cov=internal --cov=config --cov-report=term-missing`：通过，240 passed；pytest 输出显示 `VenAgent test network guard: ENABLED`，总覆盖率 59%。
- `python -m compileall -q final`：通过。
- `docker compose -f final/docker-compose.yml config --quiet`：通过，使用临时进程环境变量，仅做配置解析，未启动服务。
- `git diff --check`：通过；仅有 Git 对现有换行格式的提示。

## 遗留项

- 补充 chat/RAG/tool/document 共享行为 fixtures。
- 59% 是当前 legacy 全量基线；未达到 80% 门槛，后续重构应提高关键路径覆盖率。

## 测试网络安全策略

`final/tests/conftest.py` 默认安装网络熔断。需要明确批准的真实网络测试时，设置：

```powershell
$env:VENAGENT_ALLOW_NETWORK_TESTS = "1"
python -m pytest tests
```

pytest 启动头会显示 `ENABLED` 或 `DISABLED`；未设置该变量时，任何未 mock 的 `requests` 外连都会失败并提示如何定位/关闭熔断。
