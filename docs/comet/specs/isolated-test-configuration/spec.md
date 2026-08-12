# 隔离测试配置

## 目标

让本地 pytest 能够在不触碰生产数据库和不复制秘密的前提下运行真实 PostgreSQL 与 Neo4j 测试。

## 行为

- `.env` 增加 `TEST_DATABASE_URL=postgresql://venagent:${POSTGRES_PASSWORD}@127.0.0.1:5432/venagent_test`。
- `.env` 增加 `TEST_NEO4J_URI=bolt://127.0.0.1:7687`。
- PostgreSQL 夹具解析 `${POSTGRES_PASSWORD}`，并要求最终数据库名为 `venagent_test`。
- Neo4j 测试使用 `TEST_NEO4J_PASSWORD` 进程变量；本次执行从现有本机 `NEO4J_PASSWORD` 读取，不将该值写入 Comet 文件。
- 测试前确认 Compose 的 PostgreSQL 与 Neo4j 服务可用；必要时创建 `venagent_test`。
- 测试夹具从项目 `.env` 自动加载 `TEST_NEO4J_URI`，并将已有 `NEO4J_PASSWORD` 仅注入当前测试进程的 `TEST_NEO4J_PASSWORD`；不得写回任何项目文件。
- M05 持久化验收中的事实、来源、删除确认和作业状态由 PostgreSQL 验证；图边、图投影版本和一跳召回由 Neo4j `MemoryGraphStore` 验证。
- PostgreSQL adapter 不提供或恢复 `edges`、`replace_edges` 旧接口；测试必须通过 `GraphMemory` 组合 Neo4j 图端口访问 G1。

## 非目标

- 不修改 `.env.example`、应用运行时代码、数据库 schema 或生产数据；允许更新测试夹具与持久化验收测试以反映上述 adapter 所有权。
