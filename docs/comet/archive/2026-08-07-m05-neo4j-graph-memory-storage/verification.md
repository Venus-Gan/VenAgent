# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0389a10bf49926325f84424dcea70bc7fd118b998004d8938b0df5d01f7582c0",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "tests/test_neo4j_graph_memory.py"
    ]
  },
  {
    "acceptance_id": "acceptance-0f5d8c96ed3b9da7842ddb343ae25e31f2a7d946147eefc2c785359d02374baf",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "tests/test_memory_graph_store.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1e06c27be59162d7d36dd3f66e56f61a40f162a38240e991d3d016c0f26988a0",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "tests/test_memory_graph_store.py"
    ]
  },
  {
    "acceptance_id": "acceptance-3ce76bc477f76dac1af15079316313b41d07cfed40f96ae63f8d6f29c54a9557",
    "evidence_refs": [
      "tests/test_memory_graph_store.py",
      "tests/test_neo4j_graph_memory.py"
    ]
  },
  {
    "acceptance_id": "acceptance-5fc0c74c5ee527854b6f4ed2d6c1337b7633088e459c3b7e769dcc9df8e67509",
    "evidence_refs": [
      "venagent/infra/memory/neo4j/graph.py",
      "venagent/infra/platform/neo4j/migrations.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a184e141a52d86314b396fedda43d93ac163c994050e76441ddb8bfbf147beca",
    "evidence_refs": [
      "tests/test_config.py",
      "tests/test_memory_context.py",
      "venagent/infra/platform/neo4j/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a239bf8666e096d9d7cb3bb66b104aadaa8898c6f73288052c7d112d3adc1bab",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/memory/recall_provider.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a2aa7cd1c18c65af43ab7bb3de9c6ae785cbe7222bfa0469e6ee0fedde6fce0c",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/infra/memory/postgresql/jobs.py",
      "venagent/infra/memory/postgresql/long_term.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b4b0c286a70b26b3827487c7f3cc9b1009522617b0a551a008aab987c6efbc9c",
    "evidence_refs": [
      "tests/test_neo4j_graph_memory.py",
      "venagent/infra/memory/neo4j/graph.py"
    ]
  },
  {
    "acceptance_id": "acceptance-e2de09ac111aced0a5bd0a339a379ffc82560c28010c6bf3eef4f088c54ec223",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/infra/platform/migrations.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-ec9413d674536db7515d89060a865030a36d12c036c5df29a30d1f0dcbd246e9",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/memory/write_pipeline.py"
    ]
  },
  {
    "acceptance_id": "acceptance-fcfbf8ef78af30f6bc5a34743e6f3f8c02c7e52c0524f401bf3bbedc738e42a5",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/infra/memory/postgresql/jobs.py",
      "venagent/infra/memory/postgresql/long_term.py"
    ]
  },
  {
    "acceptance_id": "acceptance-fd79eff69ca7113779b416a69b7769835e62f55b293acafc880da0e1c6ad73f8",
    "evidence_refs": [
      "tests/test_memory_maintenance.py",
      "venagent/memory/maintenance.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `comet native check m05-neo4j-graph-memory-storage`：通过，receipt 为 `runtime/evidence/check-receipts/7cff3812f394079373a95a6682c31d95de5ea4274295ec68a40a1136ecd5f2ae.json`。
- `python -m pytest tests -q --ignore=tests/test_persistence.py`：167 passed，1 skipped。
- `python -m pytest` 四项非真实数据库 persistence 用例：4 passed。
- `python -m ruff check venagent tests`：通过。
- `python -m compileall -q venagent`：通过。
- 注入临时非秘密验证值后执行 `docker compose --env-file .env.example config --format json`：配置解析通过，Neo4j 7474/7687 均生成 `host_ip: 127.0.0.1`。

# Skipped checks

- 真实 PostgreSQL 集成测试未运行：现有项目 PostgreSQL 卷属于既有数据，当前无运行容器，未对该卷执行启动、清理或迁移。
- 真实 Neo4j 往返测试未运行：本机没有 Neo4j 镜像/卷，也没有用户提供的隔离测试密码；对应测试明确 skipped，未用模板凭据启动持久服务。

# Spec consistency

实现边界、revision/generation fencing、异步维护、降级语义与已批准规格一致。首轮 Verify 发现的 Compose 网络暴露已修复：Neo4j 默认只绑定 loopback，模板密码为空且 Compose 要求显式注入。

# Known limitations and risks

- 尚未在真实 Neo4j 5.26 容器执行 constraints、事务替换和一跳读取。
- 尚未在真实 PostgreSQL v7 数据库执行前向 v8 迁移。

# Conclusion

通过。13 项验收均有项目内证据，自动化与静态检查通过；真实数据库集成限制已如实记录，不伪造为已执行。
