# project-verification-tooling

## 1. 项目级 Python 质量工具

VenAgent SHALL 将 Ruff 声明为 `pyproject.toml` 中的项目开发依赖，并在同一文件维护 Ruff 配置。开发者 SHALL 能在项目 `.venv` 中通过 `python -m ruff` 运行检查，而不依赖全局安装。

当前 Ruff 必检范围 SHALL 为活跃 Python 源码 `venagent/` 与测试 `tests/`。退休或仅供参考的 `final/` SHALL NOT 因本能力被批量格式化或纳入当前质量门槛。

## 2. 真实 PostgreSQL 测试连接

真实 PostgreSQL 集成测试 SHALL 只使用专用变量 `VENAGENT_TEST_DATABASE_URL`，并连接与开发数据库隔离的测试数据库。进程环境中的值 SHALL 优先；未显式设置时，测试装配 MAY 从被 Git 忽略的仓库根 `.env` 读取该变量。

未配置专用测试连接时，真实集成测试 MAY 诚实跳过；配置后 SHALL 实际执行，不得将内存 adapter、mock、静态 schema 检查或开发数据库冒充为隔离的真实数据库证据。

## 3. 秘密与数据隔离

真实数据库密码和完整连接串 SHALL NOT 写入 tracked 文件、Comet 产物、日志或测试失败消息。仓库中的模板与说明 SHALL 只包含变量名和非秘密占位值。

真实集成测试 SHALL NOT 对开发数据库执行 migration、清理或写入测试记录。默认本机方案使用同一 PostgreSQL 实例中的独立 `venagent_test` 数据库。每个真实用例 MAY 在该隔离数据库内清理 VenAgent 业务数据，但 SHALL 保留 schema migration 与 LangGraph checkpointer schema。

## 4. PostgreSQL 恢复、并发与 fencing 证据

真实 PostgreSQL 测试 SHALL 验证 migration、业务记录持久化以及 runtime 重建后的恢复。

真实并发领取测试 SHALL 使用至少两个独立 PostgreSQL runtime/连接池同时竞争唯一 queued run，并证明恰好一个 worker 获得首次 claim；不得用单连接顺序调用或内存 adapter 代替。

真实 lease 接管测试 SHALL 证明：

- 首个 worker 领取后的 `execution_attempt` 为 1；
- lease 到期后第二个 worker 能领取同一 run，获得不同 claim token 且 `execution_attempt` 增为 2；
- 首个 worker 的旧 token/attempt 无法 heartbeat、完成或终结当前 run；
- 当前 worker 能完成 run，且正式 assistant message 只写入一次。

## 5. 验证契约

项目验证 SHALL 能分别证明：

- 项目虚拟环境内的 Ruff 对活跃 Python 范围检查通过；
- 配置专用连接后，真实 PostgreSQL 恢复、并发领取与 fencing 用例执行并通过且不再 skipped；
- 全量 pytest、Python 静态编译和文本卫生检查没有因测试强化产生回归；
- 证据与输出未泄露数据库秘密或完整连接串。
