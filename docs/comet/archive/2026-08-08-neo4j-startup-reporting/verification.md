# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0e446bfece7fbe189439f4b34ecf012d9f7d09219d824df9aa22d7ed7a2cbc9e",
    "evidence_refs": [
      "tests/test_startup_reporting.py",
      "venagent/bootstrap.py",
      "venagent/infra/platform/neo4j/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-106dd9315732abddb06b67b76aa7e4bf6ccf0b51b33bdda0c46d0709806663e1",
    "evidence_refs": [
      "tests/test_startup_reporting.py",
      "venagent/bootstrap.py",
      "venagent/infra/platform/neo4j/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-2b082d115289e5c75adb570bbe649f275ad4e609052e9ce3a0c5a057896879f9",
    "evidence_refs": [
      "tests/test_startup_reporting.py",
      "venagent/bootstrap.py",
      "venagent/infra/platform/neo4j/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c5e2866217efdd188a57346b2c390366fdfa3fa857d0d63faacfd0a0f01f0550",
    "evidence_refs": [
      "tests/test_startup_reporting.py",
      "venagent/bootstrap.py",
      "venagent/infra/platform/neo4j/runtime.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\.venv\Scripts\python.exe -m pytest -q -rs tests\test_startup_reporting.py`：13 passed；覆盖 Neo4j ready、not configured、durable identity required、connection/schema unavailable、启动顺序和 `/health` 映射。
- 使用真实本地 PostgreSQL/Neo4j 执行 application `open()` 并调用通用启动报告器：通过；保留 `healthy -> recovering -> healthy` 两条能力事件，随后依次输出 PostgreSQL ready、Neo4j ready、四项原有记忆能力。
- 真实启动汇总为 `6 项可用、0 项降级、0 项未启用、0 项失败`；Neo4j 文案为“Neo4j 连接正常，图存储 schema 与当前版本兼容。”。
- 真实 application health 中 `infrastructure.neo4j` 为 `status=connected`、`state=ready`、`reason_code=neo4j_ready`。
- `.\.venv\Scripts\python.exe -m pytest -q -rs tests\test_startup_reporting.py tests\test_config.py tests\test_api.py tests\test_memory_context.py tests\test_neo4j_graph_memory.py`：71 passed。
- `.\.venv\Scripts\python.exe -m ruff check venagent\bootstrap.py venagent\infra\platform\neo4j\runtime.py tests\test_startup_reporting.py`：通过。
- `.\.venv\Scripts\python.exe -m compileall -q venagent`：通过。
- `.\.venv\Scripts\python.exe -m pytest -q`：182 passed、3 failed；失败集合仍仅为 `tests/test_test_configuration.py` 调用既有夹具中不存在的 `_load_local_test_database_url`，与本 change 无关。
- `node D:\NVM\nodejs\node_modules\@rpamis\comet\bin\comet.js native check neo4j-startup-reporting --json`：通过；3 个 scope 文件无文本安全问题，receipt 为 `runtime/evidence/check-receipts/5770199cd81f545965a0ecb38d2e413996a41c64e4d3f3c11ea02318d1a5bf46.json`。

# Skipped checks

- 未破坏性修改 Neo4j schema 或停止容器来制造真实故障；connection/schema unavailable 使用不含秘密的 fake driver 故障注入覆盖。
- 未改动 `GraphMemory` 与“关联图谱召回”能力文案、状态转换或业务行为，因此未增加记忆召回质量评测。

# Spec consistency

- Neo4j driver/runtime 只持有基础设施连接与 schema 状态；GraphMemory 能力仍由 `MemoryCapabilityRegistry` 持有。
- composition root 只按 PostgreSQL、Neo4j、记忆能力顺序聚合，不在通用报告器或 HTTP 层增加组件判断。
- `/health` 与启动日志读取同一个 `Neo4jRuntime.infrastructure`；没有重新连接、探测或从中文文案反推状态。
- 日志只包含稳定 reason 与预定义中文文案，不包含 URI、用户名、密码或原始异常。

# Known limitations and risks

- 完整根 pytest 仍有 3 个既有测试夹具 API 漂移失败：`tests/test_test_configuration.py` 期望 `_load_local_test_database_url`，而 `tests/conftest.py` 当前只提供 `_load_local_test_environment`。该问题不影响本 change 的四项验收，但全套 pytest 尚非全绿。
- Neo4j infrastructure 是 application lifespan 完成连接/schema 校验后的启动状态快照；运行期 GraphMemory 能力降级继续由 capability registry 反映，不会把一次能力调用失败误写成新的启动连接结论。

# Conclusion

Neo4j 已作为独立基础设施出现在 PostgreSQL 之后、四项原有记忆能力之前，并同步到 `/health`。健康真实环境汇总为 6 项可用；未配置和连接/schema 失败路径均使用独立安全状态。四项验收通过，既有 3 个无关测试失败已明确记录。
