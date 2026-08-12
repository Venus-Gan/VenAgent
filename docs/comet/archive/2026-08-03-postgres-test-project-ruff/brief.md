# Outcome

让 VenAgent 的真实 PostgreSQL 集成测试能够使用本机现有 PostgreSQL 实例中的隔离测试数据库运行，并将 Ruff 作为仅属于本项目虚拟环境的开发工具接入，使后续验证不再因缺少显式测试连接串或全局 Ruff 而留下证据缺口。

# Scope

- 在本机被 Git 忽略的 `.env` 中设置真实 `VENAGENT_TEST_DATABASE_URL`，连接到独立的 `venagent_test` 数据库。
- 确保本机 PostgreSQL 实例中存在隔离测试数据库，并运行真实持久化集成测试。
- 让 pytest 在进程环境未显式覆盖时安全读取 `.env` 中的专用测试连接串，但不回显或提交秘密。
- 在 `pyproject.toml` 的 `dev` extra 中加入 Ruff，并加入适合当前 Python 3.11 活跃代码的项目级配置。
- 更新非秘密模板/开发说明，明确测试数据库与项目级 Ruff 的使用方式。

# Non-goals

- 不把数据库密码、JWT secret、LLM key 或完整真实连接串提交到仓库、Comet 产物或测试输出。
- 不使用开发数据库 `venagent` 直接执行会改变 schema 或测试数据的集成测试。
- 不全局安装 Ruff，不引入新的全局命令依赖。
- 不借本 change 重排或格式化旧参考目录 `final/`，也不修改业务行为。

# Acceptance examples

- 本机 `.env` 包含有效的 `VENAGENT_TEST_DATABASE_URL`，其目标数据库为 `venagent_test`；运行 `.venv\\Scripts\\python.exe -m pytest -q tests\\test_persistence.py` 时真实 PostgreSQL 用例通过且不再 skipped。
- 测试数据库与开发数据库隔离，执行 migration、写入 run、关闭并重建 runtime 后可验证恢复，开发库数据不受影响。
- 执行 `.venv\\Scripts\\python.exe -m pip install -e ".[dev]"` 后，`.venv\\Scripts\\python.exe -m ruff check venagent tests` 可在项目虚拟环境中运行并通过。
- 新检出的仓库能够从 `.env.example` 和 README 得知如何配置专用测试数据库，但看不到任何真实密码或完整真实连接串。

# Constraints and invariants

- 显式进程环境中的 `VENAGENT_TEST_DATABASE_URL` 优先于 `.env`；缺失时仍允许真实集成测试诚实跳过。
- `.env` 继续被 Git 忽略；任何诊断、报告和 Comet 摘要不得暴露连接串。
- Ruff 只检查当前活跃 Python 源码 `venagent/` 与 `tests/`；退休/参考实现 `final/` 不纳入本次质量门槛。
- 使用现有 PostgreSQL 16 容器/实例，不为项目常驻第二套数据库服务。

# Decisions

- 使用同一 PostgreSQL 实例中的独立数据库 `venagent_test`，不复用开发数据库。
- Ruff 放入 `[project.optional-dependencies].dev`，配置放入 `pyproject.toml`，通过虚拟环境中的 `python -m ruff` 调用。
- 本机真实连接串只写入 `.env`；仓库只保存变量名、占位示例和安全装配逻辑。
- 用户已确认以上范围、隔离数据库方案、项目级 Ruff 方案和验收标准。

# Open questions

- 无。

# Verification expectations

- 真实 PostgreSQL 集成测试必须实际执行并显示通过而非 skipped。
- 全量 pytest 回归通过，并如实记录其他跳过项。
- 项目虚拟环境中的 Ruff 对 `venagent/` 与 `tests/` 检查通过。
- `python -m compileall`、`git diff --check` 和 Comet 文本检查通过。
- 检查 Git/Comet 证据中不存在真实连接串或密码。
