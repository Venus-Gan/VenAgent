# Sprint 03 TDD 报告

## 范围

- P1-06：迁移 `_bootstrap_concurrent`
- P1-07：FastAPI lifespan 装配/关闭
- P1-08：capability health 与降级模型

## RED

1. 首次运行新测试时，导入路径测试设置缺失，先修正测试路径使其与 Sprint 02 测试一致。
2. 修正路径后，`venagent.bootstrap.concurrent`、`apps.api.lifespan` 和 `venagent.infrastructure.health` 均因尚未实现而真实失败。
3. 生命周期测试初始依赖 `pytest-asyncio`，发现当前环境未安装；改为标准库 `asyncio.run()`，未新增依赖。

## GREEN

- 新并发、生命周期、health 和 Sprint 02 Bootstrap 定向测试：36 passed。
- 加入 FastAPI app factory lifespan 集成断言后：定向测试 23 passed。
- 延迟专项审查收口回归首次运行：15 failed，失败点分别覆盖 app factory 懒启动、cleanup diagnostics、memory writer 排空、socket guard 和旧入口回滚。
- 修复后定向收口测试：41 passed。
- 全量测试：295 passed。

## REFACTOR

- 移除 Agent 构造器中的并发线程、恢复、RAG 已有数据检查、KG 初始化和 memory writer worker 启动。
- 将同步生命周期 hook 放入 `asyncio.to_thread()`，避免阻塞事件循环；异步 hook 直接 await。
- memory writer 改为显式 start/stop，stop 先排空队列并无超时等待 worker 结束。
- app factory 改为只创建 app shell，资源装配延迟到 lifespan；app state 不再保存完整依赖或生命周期管理器。
- lifecycle startup 追踪部分初始化资源，报告 cleanup failures；同步 hook 取消时等待线程完成。
- `initialize_runtime()`、`build_deps()` 增加失败回滚；并发结果按完成顺序归集并明确取消策略。
- 测试网络熔断扩展到 socket 层，同时保留 loopback 供 asyncio 测试基础设施使用。
- 任务结果、生命周期错误和 health snapshot 不保存原始异常文本、DSN 或 secret。
- 保留 `_bootstrap_concurrent()` 作为兼容包装，但不再包含线程编排实现。

## 验证结果

```text
python -m pytest tests
295 passed

python -m pytest tests --cov=../src/venagent --cov-report=term-missing
295 passed
整体 src/venagent 覆盖率：94%

python -m compileall -q final src apps
通过

新 src/venagent 与 apps 代码导入 final 的 AST 检查
通过，无违规

git diff --check
通过（仅保留既有 LF/CRLF 提示）
```

所有 pytest 输出均确认网络熔断为 ENABLED；requests 和 socket 层均未连接真实 LLM、HTTP、数据库、MCP 或 Docker。
