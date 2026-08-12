# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-8cebf975ce6bb02e14d6d2469e9709a7a22697e94d2fb221b5b717785a9e3633",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "venagent/agent/context.py",
      "venagent/memory/recall_provider.py",
      "venagent/memory/write_pipeline.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a1c931a8adea65de974eb224bf6327d94dc558b216d899933f831e251bf6cbcd",
    "evidence_refs": [
      "tests/test_conversation.py",
      "venagent/conversation/ports.py",
      "venagent/conversation/service.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a26457afaba37a12c027978a667039b68996d705d5173dac8cc6f1fe7d754d04",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/infra/memory/postgresql/long_term.py",
      "venagent/infra/memory/postgresql/short_term.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a4e474b3bc2f2053ee3fb5e8b0b2a7433ff91365ebfa6e92b3dfaeccdcf10c96",
    "evidence_refs": [
      "tests/test_config.py",
      "tests/test_llm.py",
      "venagent/infra/config/loader.py",
      "venagent/infra/llm/config.py"
    ]
  },
  {
    "acceptance_id": "acceptance-be2dab5cbcb1aa4ebc9efda46bec6d4ce7750be0c07cdb7baabe2c0b7eb7c8a2",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "tests/test_persistence.py",
      "venagent/infra/platform/migrations.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c37b4df884e25b906368fd5bad6d4ce41a559aa4ef6a34d78ab223c938f46994",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "venagent/agent/errors.py",
      "venagent/agent/ports.py",
      "venagent/memory/errors.py",
      "venagent/ownership/ports.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c37bd3c8afb1ae8bead332f5e14faae48408af0a5a035ca104143ede8e1d0741",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "tests/test_persistence.py",
      "venagent/infra/platform/postgresql/conversation_runtime.py",
      "venagent/infra/platform/temporary/conversation_runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-d3a5cc4290579e17d8f21af2c8690bbf3fece8e5a50e4828fa09399dfd3e7218",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "venagent/bootstrap.py",
      "venagent/interfaces/http/app.py"
    ]
  },
  {
    "acceptance_id": "acceptance-fe00ce8c24fd48516bcebdf7694b2b782e87b1c51cd2e734e62c97f4b7076cc7",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "venagent/memory/long_term.py",
      "venagent/memory/short_term.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\.venv\Scripts\python.exe -m pytest -q`：通过，156 项测试全部通过（20.74 秒），覆盖正常、失败、边界、隔离、配置和既有 M05 行为。
- `.\.venv\Scripts\python.exe -m pytest tests\test_persistence.py -q`：通过，连接本机 Docker 中的 PostgreSQL 16 执行 10 项真实持久化集成测试（13.97 秒）。
- `.\.venv\Scripts\python.exe -m ruff check venagent tests evals`：通过，无 Ruff 问题。
- `.\.venv\Scripts\python.exe -m compileall -q venagent tests evals`：通过，无 Python 编译错误。
- `npm.cmd run build`（`web/`）：通过，Vue TypeScript 检查与 Vite 生产构建完成，共转换 32 个模块。
- `docker compose ps --format json`：PostgreSQL 容器 `venagent-postgres-1` 正在运行且状态为 `healthy`，端口 5432 可用。
- `node D:\NVM\nodejs\node_modules\@rpamis\comet\bin\comet.js native check refactor-memory-module-layout --json`：通过；receipt 为 `runtime/evidence/check-receipts/45a113298bd99c2a55d7a8507b3a13042f5457d857c5b20959cd889efb1141e9.json`，扫描 66 个实现范围文本文件和 492758 字节，未发现问题。

# Skipped checks

- 未运行 mypy、Bandit 和 pip-audit：本 change 没有把这些可选外部工具设为硬门槛；已用 pytest、Ruff、编译检查、Comet 范围检查和人工边界复核覆盖当前重构风险。
- 未执行新的数据库 schema 迁移：本 change 只重排 adapter 与连接资源所有权，没有修改业务表结构；现有 PostgreSQL 集成测试直接验证兼容性。
- 未发起真实第三方 LLM 请求：配置迁移使用离线、无真实凭据的测试验证，避免泄露密钥或依赖外部服务状态。

# Spec consistency

活动 Python 包保持 feature-first。`memory/` 的短期、长期、图、召回、写入、管理与授权职责已按业务文件拆分，`service.py` 仅保留用例门面；`agent/context.py` 仍拥有最终上下文预算投影。conversation、agent、ownership 和 memory 分别定义消费方 port 与错误边界，接口层只消费服务，具体 adapter 仅位于 `infra/`，并由 `bootstrap.py` 装配。

配置来源已统一为代码安全默认值、仓库根 `.env` 和显式进程环境，后者优先；活动实现不再读取 YAML。`.env.example` 与本地 `.env` 均按配置分组添加说明注释，测试验证类型转换、未知结构化键快速失败、显式环境覆盖和秘密不回显。

所有业务 PostgreSQL adapter 共享 `infra/platform/runtime.py` 创建并注入的同步 psycopg 连接池。官方异步 LangGraph checkpointer 因 API 模型不同使用同一 runtime 所有的独立异步池；migration CLI 使用短生命周期直连。FastAPI route 不接收原始连接，项目没有 SQLAlchemy `sessionmaker` 或 `get_db` 依赖函数。

# Known limitations and risks

- `infra/memory/postgresql/` 与 `infra/platform/postgresql/` 仍是两个目录，但只表达不同 feature port 的 adapter 所有权，不各自创建数据库 runtime；这一不变量由架构测试约束。
- 同步业务池和异步 checkpointer 池是两个物理连接池，这是 psycopg 同步 adapter 与 LangGraph 异步 checkpointer API 的必要分离；两者的配置、创建和关闭仍只有平台 runtime 一个所有者。
- 本地 `.env` 仅用于开发且保持 Git 忽略；生产部署仍需由进程环境或 Secret Manager 注入同名变量。

# Conclusion

通过。目录重构、环境配置统一、PostgreSQL 资源所有权与全部 Runtime 派生验收项均有实现和自动化证据；全量测试、真实 PostgreSQL 集成、静态检查、编译、前端构建及实现范围文本检查全部通过。
