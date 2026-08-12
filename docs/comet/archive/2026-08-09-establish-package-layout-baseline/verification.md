# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-06fb63790b30c47d0a1e1e4596adb42102c0150ca28f7f869e9673a4f9519bb4",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "tests/test_persistence.py",
      "venagent/repo/postgresql/conversation_runtime.py",
      "venagent/repo/temporary/conversation_runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-0fc9627cd08f22c26175f3f5495d0cca116e928eb896089915fb453df6f2aa73",
    "evidence_refs": [
      "tests/test_agent_loop.py",
      "tests/test_memory_context.py",
      "venagent/promptctx/assembler.py",
      "venagent/promptctx/context.py",
      "venagent/promptctx/recall_provider.py"
    ]
  },
  {
    "acceptance_id": "acceptance-9d26ded7e0c109912be1330d72a328cd4b8d5b06df334c80d54632e211ce3eb4",
    "evidence_refs": [
      "README.md",
      "tests/test_package_layout.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b25451a41891fe7d5fb20de6642ef1461c76579e1e2852ff87bd4eb46d97f625",
    "evidence_refs": [
      "tests/test_api.py",
      "tests/test_package_layout.py",
      "tests/test_streaming_api.py",
      "venagent/interfaces/http/app.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b5608610b8cdde06dd57b0d890f963fadbe1885dfc2e898cc72a2881de3b201b",
    "evidence_refs": [
      "README.md",
      "tests/test_package_layout.py"
    ]
  },
  {
    "acceptance_id": "acceptance-e902d631d51f4746b6ac60f7b5b426fe8ccf0f732c51e2b4fe97d0c5b38bdff9",
    "evidence_refs": [
      "README.md",
      "tests/test_package_layout.py",
      "venagent/bootstrap.py",
      "venagent/platform/postgresql/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f81d5281e7e5b2bb7be1095fb34f3b5409b994601ee23bac83dd89443374e48d",
    "evidence_refs": [
      "README.md",
      "venagent/memory/long_term/facts.py",
      "venagent/memory/long_term/policy.py",
      "venagent/memory/long_term/writer.py",
      "venagent/memory/service.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.venv\Scripts\python.exe -m pytest -q`：通过，186 passed，覆盖架构、配置、HTTP/SSE、conversation/run、memory、真实 PostgreSQL 与 Neo4j 集成测试。
- `.venv\Scripts\python.exe -m pytest -q tests/test_package_layout.py tests/test_conversation.py tests/test_runs.py tests/test_agent_loop.py tests/test_memory_context.py tests/test_memory_evals.py tests/test_memory_graph_store.py tests/test_memory_maintenance.py`：通过，64 passed。
- `.venv\Scripts\python.exe -m pytest -q tests/test_memory_context.py tests/test_memory_evals.py tests/test_memory_graph_store.py tests/test_memory_maintenance.py tests/test_neo4j_graph_memory.py tests/test_agent_loop.py`：通过，55 passed。
- `.venv\Scripts\python.exe -m pytest -q tests/test_persistence.py`：通过，13 passed，验证真实 PostgreSQL adapter、事务和 runtime 装配。
- `.venv\Scripts\python.exe -m ruff check venagent tests`：通过，All checks passed。
- `.venv\Scripts\python.exe -m compileall -q venagent`：通过，退出码 0。
- 生产 Python 文件行数检查：无超过 800 行的活动文件。
- 旧路径扫描：活动 Python 与测试中不存在 `venagent.infra`、`agent.context`、旧 memory 模块或单体 HTTP `routes.py` 导入。
- `comet native check establish-package-layout-baseline --json`：未完成扫描；receipt `runtime/evidence/check-receipts/3ffa68c2a1fcc221610ed535568fd474ff8660abe037fd0ec69abb3324e1ff9f.json` 返回 `scan-limit`，75 个文件已选择但 0 个文件被扫描，未报告代码内容问题。

# Skipped checks

- 未运行浏览器 E2E：本 change 未修改 `web/`，现有 HTTP/SSE 用户契约由 pytest API 与 streaming 测试覆盖。
- 未把失败的 Comet 文本检查 receipt 作为通过证据；其限制已在命令结果和已知风险中记录。

# Spec consistency

- 活动 `venagent/infra/` 已移除，技术职责分别归入 `config/`、`llm/`、`platform/` 与 `repo/`；`bootstrap.py` 是唯一 adapter composition root。
- `promptctx/` 独立拥有 ContextBlock、ModelCallContext、预算、policy、source 与装配；memory 只负责授权、生命周期、候选召回和排序，agent 只负责运行编排。
- `MemoryService` 保留稳定 façade，但改为显式组合 `MemoryAuthorizer`、`MemoryManager`、`LongTermWriter`、`MemoryJobs` 与 `MemoryRecall`；消费方使用窄 memory Protocol。
- temporary 与 PostgreSQL adapter 使用对称职责文件，连接池只由 `platform/postgresql/runtime.py` 创建；HTTP 不直接取得数据库连接。
- README 已同步逐项注释的 M01--M05 活动树；M06--M09 只保留规划原则，未预建目录或空实现；`final/` 仍仅作为参考且不在 implementation scope 内。

# Known limitations and risks

- implementation scope 因大规模目录迁移折叠了 29 项展示明细；完整 scope 中 0 项未归属。用户已确认该 partial allowance，风险仅限 Comet 展示预算，不代表未知文件变化。
- Comet 内置 scoped-text-safety 检查在扫描前命中 `scan-limit`。项目侧 Ruff、compileall、路径扫描和 186 项 pytest 均通过，但本次归档不声称该内置文本检查通过。
- HTTP lifespan 继续承载既有跨领域删除/回收协调顺序，这是已批准的边界例外，不作为后续模块范式。

# Conclusion

PASS。七项 acceptance 均有项目内证据，目录所有权、显式组合、adapter 对称性、资源生命周期与用户行为符合已批准契约；已知限制已明确记录且不改变实现正确性结论。
