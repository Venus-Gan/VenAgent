# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-159139178358c26116f809c88f4c5f3a9dd7c1075ad20ec685b1f837158af577",
    "evidence_refs": [
      "tests/test_agent_loop.py",
      "tests/test_memory_index.py",
      "tests/test_startup_reporting.py",
      "venagent/memory/jobs.py"
    ]
  },
  {
    "acceptance_id": "acceptance-3d70866193d943d3bc3268726b19f87bede5b1b01961607bc96996991da6fa21",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "tests/test_memory_semantics.py",
      "venagent/memory/long_term/conflict.py"
    ]
  },
  {
    "acceptance_id": "acceptance-568981468813b0879f7a8d690050e3446bf810d850fdbd6bcb0b536dcb9f2159",
    "evidence_refs": [
      "evals/memory/recall_gold_v1.jsonl",
      "tests/test_memory_index.py",
      "venagent/memory/recall.py"
    ]
  },
  {
    "acceptance_id": "acceptance-7d8d41ffc91a82be93e190c15abb266b3c23a41a75a0c5bba8763282683f2a81",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "tests/test_memory_index.py",
      "venagent/promptctx/recall_provider.py"
    ]
  },
  {
    "acceptance_id": "acceptance-88e0461aa8b0b517c075a1c38726fde25c7033d1f49189a63f3d2ac974385c57",
    "evidence_refs": [
      "tests/test_memory_index.py",
      "tests/test_memory_semantics.py",
      "web/tests/e2e/memory.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-b91d331b33047bd68da23d4f4e83c9c32e93fea76e8f60b0e584e01eb89ad82d",
    "evidence_refs": [
      "tests/test_api.py",
      "tests/test_memory_context.py",
      "venagent/memory/command_adapter.py"
    ]
  },
  {
    "acceptance_id": "acceptance-bd9e3e63209160364c313144d906737f6975b6a69f8353e45ad749d560555c60",
    "evidence_refs": [
      "evals/memory/store_policy_v1.jsonl",
      "tests/test_memory_semantics.py",
      "venagent/memory/long_term/policy.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f3809cdc875bdd9da234a1d2cb2d4d729c712c7aaada796604d1cf889a0f6192",
    "evidence_refs": [
      "web/src/modules/chat/store.ts",
      "web/tests/e2e/memory.spec.ts"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\.venv\Scripts\python.exe -m pytest -q --ignore=tests\test_persistence.py --ignore=tests\test_neo4j_graph_memory.py`：194 passed，20.58 秒；scope 重新封印后复跑为 194 passed，22.71 秒。
- `.\.venv\Scripts\python.exe -m pytest -q tests\test_persistence.py -k 'unconfigured_persistence or schema_validation_failure'`：2 passed，11 deselected。
- `.\.venv\Scripts\ruff.exe check venagent tests evals`：All checks passed。
- `.\.venv\Scripts\python.exe -m compileall -q venagent evals`：通过，无输出。
- `npm.cmd run build`（`web/`）：`vue-tsc -b` 与 Vite production build 通过，32 modules transformed。
- `npm.cmd run test:e2e -- tests/e2e/memory.spec.ts`（`web/`）：真实 Chrome，1 passed；覆盖注册、写入、刷新、新 conversation 回忆、更新、忘记、关闭/启用、删除确认和非 JSON 错误降级。
- `node ... comet.js native check complete-m05-semantic-memory --json`：passed；46 files scanned，389324 bytes，0 issues。Receipt：`runtime/evidence/check-receipts/2b531afc7930550ef3fc29ad8c6ec94139523df8d3f4edb49da1a8fac6c01f50.json`。

# Skipped checks

- 真实 PostgreSQL/Neo4j 集成未完成：本机 `.env` 配置了测试端点，但服务不可连接；包含 `test_persistence.py` 的命令在 120 秒后超时。Docker CLI 可用但 daemon 未运行，无法在本轮启动隔离容器。
- `mypy` 未运行：项目虚拟环境未安装该模块。
- Bandit 未运行：项目虚拟环境未安装该模块。
- 真实外部 LLM 与 embedding provider 未调用；结构化输出、重试、响应校验和秘密保护由固定 fake 覆盖。

# Spec consistency

- PostgreSQL 仍是事实权威；embedding `real[]` 与 Neo4j G1 仅由 durable job 派生，失败不会回滚已提交事实。
- extractor 只消费 user/tool 来源，严格校验版本、字段、置信度与原文 value span；问题、否定、假设、引用和 preference 由确定性 policy 拒绝。
- 同 slot 弱冲突进入 quarantine，显式 correction 才 supersede；模型 judge 不能绕过确定性门控。
- recall 保持 slot 精确、版本化 lexical fallback、owner/tenant 内 dense 与 G1 1-hop；进入 ContextBlock 前再次执行生命周期和来源过滤。
- extractor、embedding、index、graph 状态独立；HTTP 未处理异常统一返回安全 JSON，前端对非 JSON transport 响应稳定降级。
- v9 forward migration 只清理 memory facts/sources/jobs/summaries/index/graph authority/settings，不删除 owner、conversation、run 或 checkpoint。

# Known limitations and risks

- 目标 Playwright 用例使用真实 Chrome 和当前 Vue 应用，但后端 transport 由 Playwright route 模拟；其跨层业务语义同时由 Python application/service 测试覆盖，仍不等价于真实 PostgreSQL/Neo4j 浏览器验收。
- 旧 `web/tests/e2e/workspace.spec.ts` 仍绑定已淘汰的 `/api/threads` 与 `/api/chat/stream`。完整 18 条旧 E2E 执行时 1 条通过、5 条各超时 30 秒，随后总命令在 180 秒终止；本 change 未把该旧基线结果计为通过。
- `.env.example` 已补充 extractor/embedding 配置，但 Native 出于 environment-file 安全规则不把 `.env*` 纳入 implementation scope 或 acceptance evidence ref。

# Conclusion

当前完整 implementation scope 的本地单元、应用集成、静态检查、编译、前端构建、目标 Chrome 验收与 Comet 文本检查均通过。外部数据库、Neo4j 和真实 provider 缺少可用运行环境，已作为明确剩余风险记录；基于可执行的本地证据，本 change 的 Verify 结论为 pass。
