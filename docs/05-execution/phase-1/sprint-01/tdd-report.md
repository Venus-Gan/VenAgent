# Phase 1 / Sprint 01 TDD 执行记录

## 范围

- P1-01：不可变配置模型；
- P1-02：五层配置覆盖与深度合并；
- P1-03：失败快速、非法组合和 secret redaction。

## Red

新增 `final/tests/test_phase1_config.py`，首次执行：

```text
cd final && python -m pytest tests/test_phase1_config.py -q
```

结果：测试收集失败，`venagent` 新目标包尚未实现，确认测试先于实现运行。

## Green

实现以下新目标模块：

- `src/venagent/infrastructure/config/models.py`
- `src/venagent/infrastructure/config/merge.py`
- `src/venagent/infrastructure/config/loader.py`
- `src/venagent/infrastructure/config/__init__.py`

初次实现后定向测试为 `5 passed, 4 failed`。失败原因是严格 tuple 输入边界、CORS 环境变量命名、错误路径安全格式和 RAG 窗口校验可定位性；修复实现与测试契约后再次执行为：

```text
12 passed
```

## Refactor

- 配置模型统一使用 `extra=forbid`、`frozen=True`、`strict=True`；
- YAML/env 的 list 在模型边界规范化为 tuple，避免冻结模型内部仍可变；
- mapping 递归合并，list 整体替换，不修改任一输入层；
- 环境变量通过显式 `ENV_FIELD_MAP` 白名单进入；未知环境变量不自动注入；
- CLI 只接受调用方传入的字段覆盖，支持 dotted path；
- 配置验证错误只输出字段路径和安全错误说明，不回显输入值；
- 脱敏函数递归复制输入，不修改原始配置。

## 验证结果

| 检查 | 结果 |
|---|---|
| 定向 Phase 1 配置测试 | 12 passed |
| 完整 pytest | 252 passed |
| 网络测试策略 | ENABLED；未访问真实 LLM/HTTP/基础设施 |
| 新配置模块覆盖率 | 94% |
| `python -m compileall -q final src` | 通过 |
| `git diff --check` | 通过（仅已有 CRLF 提示） |

整体 legacy 覆盖率仍为 Phase 0 记录的 59%，本 Sprint 只要求新配置关键路径达到 80% 以上，未伪造整体项目门禁。
