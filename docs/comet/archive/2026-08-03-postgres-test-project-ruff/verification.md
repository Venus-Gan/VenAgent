# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0221aa793eda078988cb4eeeede4d217fc4deb5a249c2a8561a8e10d9b8fdebc",
    "evidence_refs": [
      "tests/conftest.py",
      "tests/test_persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-69610d119d1dd3a5476522e20f1881b81ffb73ea39ba3a3715003a472bc08557",
    "evidence_refs": [
      "README.md",
      "pyproject.toml"
    ]
  },
  {
    "acceptance_id": "acceptance-9d2b9774b91e72f734711a790d81885ffc645f2e15d6ee999fc08536161756a6",
    "evidence_refs": [
      "tests/conftest.py",
      "tests/test_persistence.py",
      "tests/test_test_configuration.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c93fab93941b87802cba080717de1d93f37df5e0aadec6ee5c26f3544044f929",
    "evidence_refs": [
      "README.md",
      "tests/conftest.py",
      "tests/test_test_configuration.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `docker ps -a` 与容器内 `psql`：复用既有 `venagent-postgres-1`（PostgreSQL 16）；容器健康，隔离数据库 `venagent_test` 已存在且当前用户为 `venagent`。
- `.venv\\Scripts\\python.exe -m pip install -e ".[dev]" --no-build-isolation --index-url https://pypi.org/simple --timeout 30`：通过；项目 editable 安装成功，Ruff 0.16.1 来自 `dev` extra 并安装在 `.venv`。
- `.venv\\Scripts\\python.exe -m ruff check venagent tests`：通过，`All checks passed!`。
- `.venv\\Scripts\\python.exe -m pytest -q -rs tests\\test_test_configuration.py tests\\test_persistence.py`：6 passed；真实 PostgreSQL migration、run 持久化与 runtime 重建恢复实际执行，没有 skipped。
- `.venv\\Scripts\\python.exe -m pytest -q -rs`：108 passed，0 skipped。
- `.venv\\Scripts\\python.exe -m compileall -q venagent tests`：通过。
- `docker compose config --services`：通过，仅输出 `postgres`，测试 URL 的字面占位不再触发 Compose 变量警告。
- `git diff --check -- README.md .env.example pyproject.toml tests venagent`：通过；仅有既有 LF/CRLF 转换提示。
- 非回显秘密匹配检查：真实 `POSTGRES_PASSWORD` 在 README、模板、pyproject、测试、运行时代码与本 change 产物中 0 命中。
- `comet native check postgres-test-project-ruff --json`：通过；36 个文本文件、0 issues；receipt 为 `runtime/evidence/check-receipts/3c1b15f548e9047dbf35ef1924494cd5f7a59dc6c5f8a33e35a6b53ce3583d96.json`。

# Skipped checks

- 无。此前长期跳过的真实 PostgreSQL 集成测试本次已实际执行并通过。
- 未运行 mypy、Bandit、pip-audit 或 AgentShield：本 change 不引入新的运行时输入面或生产数据库连接方式；已使用 Ruff、全量 pytest、真实数据库测试、人工秘密边界复核和 Comet 文本检查覆盖当前风险。

# Spec consistency

- Ruff 只声明在 `dev` extra 中并由项目 `.venv` 执行；配置位于 `pyproject.toml`，检查范围为活跃的 `venagent/` 与 `tests/`，没有把参考目录 `final/` 纳入本次门槛。
- pytest 仅在没有显式进程覆盖时从被 Git 忽略的 `.env` 读取 `VENAGENT_TEST_DATABASE_URL`；测试装配不会把该变量加入生产应用配置。
- 本机连接目标为独立 `venagent_test` 数据库，不是开发数据库 `venagent`；密码占位在加载时 URL 编码，缺少密码时不会误启用真实测试。
- `.env.example` 与 README 只保存变量名和占位模板，没有真实密码或完整真实连接串。

# Known limitations and risks

- 真实 `VENAGENT_TEST_DATABASE_URL` 位于被 Git 忽略的本机 `.env`，按安全约束不会进入 implementation scope 或归档；其有效性由本次 0 skipped 的真实数据库测试证明。
- Ruff 当前不检查参考目录 `final/`；如果该目录未来重新成为活跃运行时代码，需要单独纳入门槛并处理其历史问题。
- 本项目没有依赖锁文件；`dev` extra 使用 `ruff>=0.16,<1.0`，本次实际验证版本为 0.16.1。

# Conclusion

通过。隔离 PostgreSQL 测试已从长期 skipped 变为真实执行，项目级 Ruff 已装入 `.venv` 并通过，完整回归和秘密边界均满足已批准规格。
