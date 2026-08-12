# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0644df49b85bbe5f0e2cf91c8aabea64156abbee78b97691eea2b70e46f439c8",
    "evidence_refs": [
      "tests/test_persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1b1576f2d2166bbf72c23f2ba2c608c5f78db4bcde647a14419dda9dfd7c02bb",
    "evidence_refs": [
      "tests/test_persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-ae2f76e6c74d66fe7425634898f30a71e01509b6b95d07d5b4c12b07cb9d1459",
    "evidence_refs": [
      "tests/test_persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b68a9a750340da2f88f4ca54581e839ce8fbf0ae46e12e430338b826cd48ffa1",
    "evidence_refs": [
      "tests/test_persistence.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `docker compose up -d postgres` 与 `docker inspect`：复用既有 `venagent-postgres-1`，验证期间状态为 healthy。
- `.venv\\Scripts\\python.exe -m pytest -q -rs tests\\test_persistence.py`：5 passed，真实 PostgreSQL 恢复、双连接并发领取与 lease 接管/fencing 用例全部执行，0 skipped。
- 将 `test_postgres_concurrent_workers_claim_queued_run_once` 与 `test_postgres_expired_lease_reclaim_fences_stale_worker` 连续运行 10 轮：每轮 2 passed，共 20 次用例执行无失败。
- `.venv\\Scripts\\python.exe -m pytest -q -rs`：110 passed，0 skipped。
- `.venv\\Scripts\\python.exe -m ruff check venagent tests`：通过，`All checks passed!`。
- `.venv\\Scripts\\python.exe -m compileall -q venagent tests`：通过。
- `git diff --check -- tests\\test_persistence.py`：通过。
- `comet native check postgres-concurrency-fencing-tests --json`：通过；1 个 scoped 文本文件、0 issues；receipt 为 `runtime/evidence/check-receipts/c26d83a42d914079f4686bc030b577e2fcead6d7d151214dec91f0412df4be06.json`。

# Skipped checks

- 无。真实 PostgreSQL 用例全部执行，pytest 报告 0 skipped。
- 未运行 mypy、Bandit、pip-audit 或 AgentShield：本 change 只扩展测试，不修改生产代码、依赖或外部输入面；Ruff、真实数据库测试、全量回归和人工安全边界复核覆盖当前风险。

# Spec consistency

- 每个真实 PostgreSQL 用例先确认当前数据库名严格等于 `venagent_test`，再迁移并执行 `TRUNCATE TABLE owners CASCADE`；开发数据库不会被清理或写入。
- 并发领取测试使用两个独立 `PersistenceRuntime` 和连接池，通过线程屏障同时竞争唯一 queued run，证明仅一个 worker 获得 attempt 1 claim。
- lease 接管测试在真实数据库中确定性令首个 lease 过期，第二 worker 获得不同 token 和 attempt 2；旧 worker 的 heartbeat、succeed 与 fail 均得到 `InvalidRunTransition`。
- 当前 worker 成功完成后，消息列表只包含输入消息与唯一正式回答，没有旧 worker 输出。
- 生产 PostgreSQL adapter 与 AgentRun 状态机未修改。

# Known limitations and risks

- 测试清理固定要求数据库名为 `venagent_test`；使用其他 CI 测试库名称前必须显式调整安全白名单，不能直接指向任意数据库。
- 当前测试套件未启用 pytest-xdist；多个进程共享同一个 `venagent_test` 时，函数级 `TRUNCATE` 会互相干扰。未来启用并行测试时应为每个 worker 分配独立数据库。
- 10 轮重复运行提高了竞争稳定性证据，但不能穷尽所有 PostgreSQL 调度时序；生产可观测性与后续负载验证仍应保留。

# Conclusion

通过。此前缺失的真实 PostgreSQL 并发领取、lease 接管与 stale-worker fencing 证据已补齐；Ruff、全量回归和静态编译均通过，未发现需要修改生产实现的问题。
