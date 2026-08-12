# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-1e2dc7d1f4f12405452d93b9b50697c166db8a865d34bf837080db19e57d717d",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/agent/runtime.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-2869fe578bc92dd6d2bbaa11470950d2616d929064f757fdc423e8cb95ab1c40",
    "evidence_refs": [
      "tests/test_agent_loop.py",
      "tests/test_api.py",
      "tests/test_streaming_api.py"
    ]
  },
  {
    "acceptance_id": "acceptance-38288b5c498cd4845208570270aa5d53f0db04381aa25dd0313de6b3f42fd1e3",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-4b291724adc73edd1e77f74ea4a4c17f955950d384f9d8c1ec06386bb843b5fb",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/agent/runtime.py",
      "venagent/interfaces/http/app.py"
    ]
  },
  {
    "acceptance_id": "acceptance-4e7a893c6bbd2a6c302abb0793967086f46946e1231746644fd26f94d2b31c53",
    "evidence_refs": [
      "tests/test_commit_recovery.py",
      "tests/test_persistence.py",
      "venagent/agent/runtime.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.venv\Scripts\python.exe -m pytest tests/test_persistence.py tests/test_api.py tests/test_streaming_api.py tests/test_agent_loop.py tests/test_runs.py -q -rs`：24 passed；覆盖真实 PostgreSQL 异步图、durable FastAPI run、API/SSE、temporary 模式和运行状态机。
- `.venv\Scripts\python.exe -m pytest -q -rs`：113 passed，0 skipped；隔离 PostgreSQL 测试实际执行。
- `.venv\Scripts\python.exe -m ruff check venagent tests`：通过，`All checks passed!`。
- `.venv\Scripts\python.exe -m compileall -q venagent tests`：通过。
- `.venv\Scripts\python.exe -m pip check`：通过，`No broken requirements found.`。
- `npm.cmd run build`（`web/`）：Vue TypeScript 检查与 Vite production build 通过。
- `git diff --check -- venagent tests docs/comet/changes/fix-async-postgres-checkpointer`：通过。
- 真实 PostgreSQL 异步图验证：`ainvoke` 与 `aget_state` 成功写入和恢复 `FinalAnswer`，不再抛出 `NotImplementedError`；用例通过异步公开接口删除同一 thread。
- 真实 FastAPI/PostgreSQL 验证：run 在有界时间内进入 `succeeded`，只发布一条 assistant message；重建 runtime 后 checkpoint 与正式消息仍可读取，并通过异步公开接口完成清理。
- Windows 真实启动验证：`python -m venagent` 使用 Selector policy 启动，PostgreSQL 状态为 `connected`，服务以持久化模式监听 `http://127.0.0.1:8090`。
- 真实浏览器和真实模型验证：页面发送消息后通过既有 SSE 显示回答“对话恢复正常”，对话标题和本机可见消息数同步更新，浏览器控制台 0 error。
- 宿主网络独立模型流验证：已配置模型的异步流调用成功；受限沙箱中的连接失败被明确识别为验收环境网络边界，没有归因给应用代码。

# Skipped checks

- 未运行 mypy、Bandit、pip-audit 或 AgentShield；本 change 未新增外部输入面、权限能力或数据库 schema，已使用 Ruff、全量 pytest、真实数据库、真实 HTTP/SSE、真实模型和人工边界复核覆盖当前风险。
- 真实浏览器成功回答后没有再次刷新页面；同一持久化行为由真实 PostgreSQL FastAPI 用例的 runtime 重建与消息读取覆盖，浏览器在服务重启后恢复失败 run 的本机状态也已观察到。

# Spec consistency

- durable runtime 保留异步 LangGraph 与异步模型流，使用官方 `AsyncPostgresSaver` 和独立异步连接池；同步业务 store 的事务边界未改变。
- `thread_id=run_id`、AgentRun/State 分工、claim/lease/fencing 和 finalizer 幂等边界保持不变。
- 应用启动只验证 schema；DDL 仍只由 `python -m venagent migrate` 执行。
- checkpoint 状态反序列化后统一恢复元组不变量；没有把 LangGraph 私表或序列化结构泄漏到业务模块。
- 真实链路同时修复了 PostgreSQL 授权查询使用保留关键字别名的问题，以及 Uvicorn 在 Windows 上覆盖 Selector policy 的问题；两者均属于 durable run 成功路径的必要条件。
- 取消请求的传播速度、模型请求中断和超时策略没有改动，继续留给后续独立讨论与 change。

# Known limitations and risks

- 真实模型可用性仍取决于外部 provider 和宿主网络；自动化测试使用可控流式模型，不把外部服务稳定性作为硬门槛。
- `_DeferredAsyncPostgresSaver` 只转发当前 AgentRuntime 使用和规格要求的公开异步接口；未来启用新的 LangGraph saver 能力时，需要同步扩展 adapter 并增加真实 PostgreSQL 测试。
- 取消慢的问题仍存在，本次按已批准 Non-goals 未修改。

# Conclusion

通过。durable PostgreSQL 模式已经能够从 HTTP 创建 run，经后台 worker、异步 LangGraph checkpoint 和真实模型流完成回答；失败不再长期伪装成 `running`，重启恢复与异步删除均有真实数据库证据。
