# Outcome

恢复本地测试连接配置，并实际执行隔离 PostgreSQL 与 Neo4j 测试。

# Scope

- 在被 Git 忽略的 `.env` 中增加 `TEST_DATABASE_URL` 与 `TEST_NEO4J_URI` 非秘密配置。
- PostgreSQL 测试使用 `venagent_test`，复用现有 `POSTGRES_PASSWORD`；Neo4j 测试使用 Compose 映射的 Bolt 地址，并在测试进程中复用现有 Neo4j 密码。
- 必要时启动 Compose 服务、创建隔离测试数据库并运行真实测试。
- 修正 M05 持久化验收测试的 adapter 边界：PostgreSQL 只验证事实、来源和作业状态；G1 图投影与一跳召回通过 Neo4j 图端口验证。
- 测试夹具从 `.env` 自动加载 `TEST_NEO4J_URI`，并只在当前 pytest 进程内提供已有 `NEO4J_PASSWORD`，不复制到项目文件。

# Non-goals

- 不修改 `.env.example`。
- 不修改生产运行时代码、数据库 schema 或生产数据库 `venagent` 中的数据；允许修改测试夹具与 M05 持久化验收测试以匹配当前已批准的 PostgreSQL/Neo4j 所有权。
- 不把密码写入 Comet 产物、日志或命令输出。

# Acceptance examples

- `.env` 中的 `TEST_DATABASE_URL` 指向 `venagent_test`，不是 `venagent`。
- `TEST_NEO4J_URI` 指向本机 Compose Bolt 映射端口。
- PostgreSQL 与 Neo4j 真实测试执行通过；不可用时必须明确报告 skipped/fail 原因。

# Constraints and invariants

- PostgreSQL 测试夹具允许从 `.env` 读取 `TEST_DATABASE_URL`，并将 `${POSTGRES_PASSWORD}` URL 编码替换为已有密码。
- Neo4j 测试密码只通过当前测试进程环境注入，不持久化为新的秘密副本。
- 所有测试操作限定在隔离数据库和测试 owner/label 范围内。

# Decisions

- 用户已批准由本 change 执行测试配置恢复、容器确认、隔离库创建和真实测试。
- 测试数据库凭据复用现有本机数据库密码，不创建新密码。
- M05 图关系的唯一持久化适配器是 Neo4j；PostgreSQL adapter 不恢复旧的 `edges`/`replace_edges` 兼容接口。

# Open questions

无。

# Verification expectations

- 检查 Compose 服务健康状态和 `venagent_test` 数据库存在。
- 运行 PostgreSQL 与 Neo4j 定向真实测试，并记录结果。
- 验证 PostgreSQL 重启后事实仍可读，Neo4j 重启后 G1 图投影与一跳召回仍可读，并验证忘记操作会清除图投影。
- 运行 Comet 文本检查，确认秘密未进入 change 产物。

# Module intake

模块：M05 memory-system
基础 intake：`ecc-rules-pack-common`、`ecc-rules-pack-python`、`search-first`；已检查仓库搜索、Python 包环境，PyPI 网络查询受本机网络权限限制，GitHub CLI 未安装。
专项能力：存储与隐私审查、`security-review`；本次仅修正测试边界，不新增运行时安全面。
search-first：Extend 现有 `MemoryGraphStore`/`GraphMemory`/Neo4j 集成测试；无需新增依赖或自建 adapter。
AGI-saber：对照 `memory/longterm`、`memory/graph`、`chat/mem_writer`、`promptctx` 及记忆系统解析文档；采用“长期事实为权威、图为可重建增强投影、图不可用时降级”的职责分离。
AGI-saber 范围：优先路径为 `D:\VSCProject\AGI-saber\docs\architecture\记忆系统解析.md`；未迁移 Go 实现、表结构或目录。
目录：仅调整 `tests/conftest.py` 与现有 `tests/test_persistence.py` 的验收边界，不新增 Python package、Vue module 或共享运行时目录。
前端：本 change 不改变前端；通过后端真实持久化测试验证正常、重启、删除和图降级边界。
