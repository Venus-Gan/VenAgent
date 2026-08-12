# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-a8578cea4b103765903deecf17c13e3103396172cfb6a3ceef3efc1c42487cd9",
    "evidence_refs": [
      "tests/test_neo4j_graph_memory.py",
      "venagent/infra/platform/neo4j/migrations.py"
    ]
  },
  {
    "acceptance_id": "acceptance-acd6a02229caf87568207daa8bcf3b5a0af102dad307bb91f58d397d25e8b2ad",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/bootstrap.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b722be8213b7eed971c43ae9dff5217f8bcc99738a01671f99e6f37f81faee58",
    "evidence_refs": [
      "tests/test_migration.py",
      "venagent/infra/platform/migrations.py"
    ]
  },
  {
    "acceptance_id": "acceptance-bdb539973c45239b99bcb0b802acc0f739ff5934d5ae32f2608e6e58d150f55b",
    "evidence_refs": [
      "tests/test_migration.py",
      "tests/test_persistence.py",
      "venagent/infra/platform/migrations.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `docker compose up -d postgres neo4j` 与 `docker compose ps --format json`：通过；PostgreSQL、Neo4j 均为 `healthy`。
- 迁移前只读检查：PostgreSQL migration history 为 `[7]`，`memory_graph_authority` 缺失，`memory_edges` 存在；关键行数为 owners 2、conversations 2，其余已抽样权威/运行/checkpoint 表均为 0。
- `.\.venv\Scripts\python.exe -m venagent migrate`：通过；CLI 报告 PostgreSQL/Neo4j schema 已迁移到当前版本。
- 迁移后只读检查：history 为 `[8]`，`memory_graph_authority` 存在，`memory_edges` 不存在，`memory_jobs` 包含 `claim_token`、`registry_version`、`target_revision`；迁移前抽样表行数均未减少。
- Neo4j 只读检查：schema version 为 1，`m05_memory_identity`、`m05_projection_identity`、`m05_schema_component` 三个 constraints 完整，迁移前后 M05 memory node 均为 0。
- 应用生命周期检查：首次诊断脚本未设置 Windows Selector event-loop，按预期触发 psycopg `ProactorEventLoop` 保护；补上真实 CLI 使用的 `_configure_event_loop_policy()` 后通过。
- 完整应用装配结果：persistence 为 `durable/postgresql_ready/connected`；长期记忆、候选提取和 GraphMemory 均为 `healthy/memory_ready`。
- `.\.venv\Scripts\python.exe -m pytest -q -rs tests\test_migration.py tests\test_persistence.py tests\test_neo4j_graph_memory.py`：21 passed。
- `.\.venv\Scripts\python.exe -m pytest -q`：178 passed、3 failed；失败均为 `tests/test_test_configuration.py` 调用既有夹具中不存在的 `_load_local_test_database_url`，与本 change 的 schema、启动和记忆路径无关。
- `.\.venv\Scripts\python.exe -m compileall -q venagent`：通过。
- `.\.venv\Scripts\python.exe -m ruff check venagent\bootstrap.py venagent\infra\platform\migrations.py venagent\infra\platform\runtime.py venagent\infra\platform\neo4j tests\test_migration.py tests\test_persistence.py tests\test_neo4j_graph_memory.py`：通过。
- `node D:\NVM\nodejs\node_modules\@rpamis\comet\bin\comet.js native check neo4j-schema-compatibility --json`：通过；no-code scope 选择 0 个文件，receipt 为 `runtime/evidence/check-receipts/911302325cde6f380f9e42318ba5c6707a058635ed213f2c1781dd5f33c3dca9.json`。

# Skipped checks

- 未停止或重建 Compose volumes；迁移已在现有健康容器和既有持久 volume 上完成，不需要破坏性重建。
- 未输出或保存 PostgreSQL、Neo4j、JWT 的秘密值；本地 `.env` 仅补充随机稳定的 `JWT_SECRET`，用于满足既有 durable identity 安全契约。

# Spec consistency

- 使用既有显式 migration CLI，没有让普通应用启动执行 DDL，也没有手工改写 migration history。
- PostgreSQL v7 权威业务数据保留，旧 `memory_edges` 按既有 v8 契约移除；Neo4j v1 schema 仅幂等迁移，没有清空节点或 volume。
- 项目代码与长期规格均未修改；修复内容仅为当前本地数据库状态和被忽略的本地安全配置。

# Known limitations and risks

- 根测试套件仍有 3 个既有测试夹具 API 漂移失败：`tests/test_test_configuration.py` 期望 `_load_local_test_database_url`，而 `tests/conftest.py` 当前只提供 `_load_local_test_environment`。该问题不影响本次迁移验收，但全套 pytest 尚非全绿。
- 当前开发库没有 memory facts/sources/jobs 或 checkpoints，因此数据保留证据由 owners/conversations 的真实迁移前后计数与 v7→v8 迁移单测共同覆盖。

# Conclusion

当前本地 PostgreSQL 已从 v7 前向迁移到 v8，Neo4j v1 schema 保持兼容，稳定 JWT 配置已补齐；真实应用启动恢复 durable，长期记忆、提取与 GraphMemory 均健康。本 change 的四项验收全部通过，根测试套件的 3 个无关既有失败已明确记录。
