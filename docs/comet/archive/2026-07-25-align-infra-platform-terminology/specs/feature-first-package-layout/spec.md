# Feature-first Package Layout 完整目标规格

## 1. 目标结构

VenAgent SHALL 使用 feature-first Python package layout。`conversation` SHALL 聚合线程生命周期、对话用例和 legacy import；`agent` SHALL 聚合 LangGraph state、graph/runtime 与 run 生命周期；`infra` SHALL 实现持久化、LLM 与 PostgreSQL platform adapter；`interfaces/http` SHALL 实现 FastAPI inbound adapter。

顶层 SHALL 保留 `bootstrap.py`、`__main__.py`、`__init__.py` 与 `web/`，但 SHALL NOT 保留旧的 `agent_loop.py`、`api.py`、`conversation.py`、`llm.py`、`persistence.py`、`runs.py` 或 `streaming.py` 实现文件。

## 2. Conversation 边界

`conversation/models.py` SHALL 保存对话与 legacy import 数据模型；`errors.py` SHALL 保存稳定领域错误；`ports.py` SHALL 以 Python `Protocol` 定义 conversation 所需的线程仓储能力；`service.py` SHALL 编排线程、Agent runtime 与仓储；`threads.py` SHALL 保存进程内 busy/lease 规则；`legacy_import.py` SHALL 保存旧浏览器记录资格、规范化与 hash 规则。

Conversation package SHALL NOT 导入 `venagent.infra`、FastAPI、psycopg 或具体 LangGraph PostgreSQL saver。

## 3. Agent 边界

`agent/state.py` SHALL 定义 graph state 与消息辅助逻辑；`graph.py` SHALL 构建 LangGraph graph；`runtime.py` SHALL 提供同步/流式执行、提交窗口、导入和删除的应用入口；`runs.py` SHALL 保存 active run/cancel registry；`ports.py` SHALL 定义模型调用边界。

Agent package SHALL NOT 导入 FastAPI、psycopg 或具体 provider SDK。外部模型和 checkpointer SHALL 通过公开协议或 LangGraph 基础契约注入。

## 4. Infra 边界

`infra/platform/` SHALL 分离内存 adapter、PostgreSQL adapter、显式 schema migrations 与启动期 runtime selection。Thread repository adapter SHALL 实现 conversation-owned Protocol；conversation SHALL NOT 反向依赖 infra。

`infra/llm/` SHALL 分离配置解析与 provider factory。具体 provider SDK 的延迟导入 SHALL 留在 infra adapter 内。

PostgreSQL pool/checkpointer 的连接生命周期 MAY 位于 `infra/postgres.py` 或 platform runtime，但 SHALL NOT 泄漏到 conversation/agent 业务模块。

## 5. HTTP 与装配

`interfaces/http/schemas.py` SHALL 保存 Pydantic request/response schema；`errors.py` SHALL 保存 HTTP error mapping；`routes.py` SHALL 保存 API route registration；`streaming.py` SHALL 保存 SSE protocol adapter；`app.py` SHALL 创建 FastAPI application 并调用显式 composition root。

依赖 wiring SHALL 集中、可审计，不得散布全局 service locator。CLI `python -m venagent` 与 `python -m venagent migrate` SHALL 保持可用。

## 6. 兼容性

本重构 SHALL 保持 M01–M03 的 HTTP、SSE、Web UI、环境变量、数据库 schema、迁移、健康状态、降级、日志安全与持久恢复行为。

顶层 `venagent` SHALL 继续导出 `AgentLoop`、`AgentResult` 和 `build_local_model`。旧内部模块路径不属于稳定契约，SHALL 随真实重构移除，不建立长期 shim。

## 7. 验收

- 全量现有行为测试 SHALL 迁移到新 import path 并通过。
- 架构测试 SHALL 证明旧扁平文件不存在，并检查 conversation/agent 不引用禁止的 adapter/framework。
- PostgreSQL 真实集成、compileall、Web 脚本、依赖、Compose 和文本卫生检查 SHALL 继续通过；无法运行的外部检查必须诚实记录。
