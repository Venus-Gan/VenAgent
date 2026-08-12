# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-06eae702a7a2e2cec67aed9d83ec565ce01cc92c6bce9f073efd142a2c49ecf8",
    "evidence_refs": [
      "evals/memory/runner.py",
      "tests/test_memory_context.py",
      "tests/test_memory_evals.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1cdd77a64b7b49e5a0748c0ebc256f3fef14d79e4a9215d09361f932819a7e7d",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/infra/memory/postgresql/graph.py",
      "venagent/infra/memory/temporary/graph.py",
      "venagent/memory/ports.py"
    ]
  },
  {
    "acceptance_id": "acceptance-3c4aa9c2c1f84da37c8d692eb1f841f75d5977731b9f6318f24df887e30e8751",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/memory/recall_provider.py"
    ]
  },
  {
    "acceptance_id": "acceptance-4485fde3dab3ce9fe3830ff241881232945b68a09de3d2d2990db25009dc93a6",
    "evidence_refs": [
      "evals/memory/runner.py",
      "tests/test_memory_evals.py",
      "venagent/memory/ports.py"
    ]
  },
  {
    "acceptance_id": "acceptance-533e8765f4de43c1f743c8b95fb99f6d55bb955313f74b538f859825c517f4bd",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/memory/ports.py",
      "venagent/memory/recall_provider.py"
    ]
  },
  {
    "acceptance_id": "acceptance-ff3c0ec30d3835e3c17c30d48917f81d34752dfbe879babc8ea973d843f3f385",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/memory/recall_provider.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.venv\Scripts\python.exe -m pytest tests\test_memory_context.py tests\test_memory_evals.py -q`：39 passed；覆盖一跳限制、稳定排序、图失败回退、权威读取失败、owner/tenant 与 registry 二次过滤、authorization epoch/deletion generation 失效、temporary 单锁快照、PostgreSQL transaction SQL 契约和 G1 质量/安全对照。
- `.venv\Scripts\python.exe -m pytest tests --ignore=tests\test_persistence.py -q`：156 passed，21.13 秒；覆盖全部不依赖真实 PostgreSQL 的项目测试。
- `.venv\Scripts\python.exe -m ruff check venagent evals tests`：All checks passed。
- `.venv\Scripts\python.exe -m ruff format --check <本 change 的 7 个 Python 文件>`：7 files already formatted。
- `.venv\Scripts\python.exe -m compileall -q venagent evals tests`：通过。
- `Get-ChildItem -Recurse -File evals,tests,venagent | Where-Object Name -match g2 | Measure-Object`：Count 为 0；产品代码、评测源码、schema、测试及生成缓存中无 G2 文件。
- 人工 Python/SQL/安全复核：SQL 使用参数绑定；PostgreSQL 在一个只读 `REPEATABLE READ` transaction 中读取 settings/facts/sources/edges；temporary 在共享 `RLock` 的一次持有中复制快照；图错误使用专用异常与权威事实错误分流；输出错误不包含事实正文、来源内容或连接细节。

# Skipped checks

- 真实 PostgreSQL 集成：`.venv\Scripts\python.exe -m pytest tests\test_persistence.py -x -q` 在 4 个非数据库用例通过后，fixture 连接 `127.0.0.1:5432` 超时并报 `psycopg.errors.ConnectionTimeout`；因此未把真实 PostgreSQL snapshot 行为和重启持久化写成通过。无数据库的 adapter 契约测试已验证单事务及 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`。
- `mypy`、`bandit`、`pip-audit`、`pylint` 当前均不可用，未运行且未标记为通过。
- 未运行浏览器检查：本 change 不修改 HTTP、Vue 或用户可见表面，现有普通回答降级由 application 测试覆盖。

# Spec consistency

实现保持 `m05-g1-v1` 关系注册表、`m05-g1-recall-v2` 排序、严格注入阈值、总 limit 和最多一个 graph-only 候选不变。新增 `G1RecallSnapshot` 只包含同一 owner/tenant 的 settings、facts、sources、edges，不接受 hop 或路径参数；`MemoryRecallProviderMixin` 仍只计算 seed 的直接 `SIMILAR_TO` 邻居，并在构造块前后校验请求快照、实时 owner authorization epoch 与 deletion generation。

此前 G2 evaluator、数据入口、schema、admission 聚合与测试已全部删除；没有创建 G2 runtime、配置、索引、HTTP、Vue、M08 空壳或新依赖。拟议完整规格只替换 `g1-recall-ranking` 与 `memory-context`，把 M05 收敛为 G0/G1，并把文档知识图谱 2-3 hop 所有权明确归 M08。

# Known limitations and risks

- 当前机器 PostgreSQL 不可达，因此只取得 PostgreSQL SQL/transaction 契约测试，未取得真实服务下的隔离级别与并发集成证据；该环境缺口不影响 temporary 行为和 application fail-closed 验证，但部署前仍应在可用数据库环境复跑 `tests/test_persistence.py`。
- final epoch/generation 复核显著缩小失效快照窗口，但与任何无长事务的请求级投影一样，最终复核之后发生的新撤销由后续请求和既有 owner/delete 原子失活规则接管。
- Comet 历史 checkpoint、trajectory、scope 和旧 verification receipt 仍包含原 G2 研究记录；这些是不可改写的工作流证据，不属于产品代码或可执行 G2 资产。

# Conclusion

PASS。6 个验收项均有当前项目实现或测试证据；G2 项目资产清理完成，G1 保持严格 1-hop，并获得一致 recall snapshot、图错误安全回退、投影前 epoch/generation 复核与质量/安全评测对照。真实 PostgreSQL 集成因本机连接超时未运行，已作为剩余环境风险明确记录。
