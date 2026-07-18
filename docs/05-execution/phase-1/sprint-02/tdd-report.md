# Sprint 02 TDD 报告

## 范围

- P1-04：`apps/api`、`src/venagent/bootstrap` 骨架与显式 dependency container
- P1-05：staged Bootstrapper、阶段诊断和失败边界
- 未执行 P1-06～P1-10；未修改旧启动路径

## Red → Green → Refactor

### Red

先新增 `final/tests/test_phase1_bootstrap.py`，首次运行因 `venagent.bootstrap` 尚不存在而在 collection 阶段失败。修正测试导入引导后，仍按预期因实现缺失失败。

随后为审查发现的边界补充回归测试并确认失败：

- app 阶段失败归因；
- async factory 不能被同步 Bootstrapper 当作成功；
- 已创建资源失败时反序 close；
- 根目录入口无 `PYTHONPATH` 导入；
- `CancelledError` 清理传播；
- async close、cleanup `BaseException` 和取消 note。

### Green

实现最小组合根和 Bootstrapper 后，定向测试依次达到 6、9、10、12、14 passed。最终覆盖：

- 固定阶段顺序与成功结果；
- infrastructure/application/app 任一阶段失败；
- 稳定错误码和不泄露原始异常上下文；
- `AppConfig` 类型和 frozen container；
- fake provider 注入与无导入副作用；
- 同步/异步 factory 边界；
- 普通失败、取消和中断路径的反序清理。

### Refactor

- 让阶段失败在离开原始 `except` 后再构造公开错误，避免 `__context__` 携带 secret 异常。
- 将 cleanup 收敛为反序、best-effort、仅暴露资源类型名的安全边界。
- 使用 AST 检查 `src/venagent`/`apps` 不导入 `final`。
- 在 `apps/api/main.py` 仅加入由自身位置推导的 `src` 路径引导，保持入口可从仓库根目录导入。

## 验证结果

执行：

```text
cd final && python -m pytest tests --cov=../src/venagent --cov-report=term-missing
```

结果：`266 passed`；网络熔断输出为 `ENABLED`。新增 bootstrap 代码覆盖率 99%，整体 `src/venagent` 覆盖率 96%。

其他门禁：

- `python -m compileall -q final src apps`：通过
- `python -B -c "import apps.api.main"`：通过
- 根目录无 `PYTHONPATH` 子进程导入测试：通过
- `src/venagent` 与 `apps` 的 `final` 导入 AST 门禁：通过
- `git diff --check`：通过；仅报告已有文档的换行风格警告
- 未访问真实 LLM、数据库、MCP、HTTP 或 Docker 服务
