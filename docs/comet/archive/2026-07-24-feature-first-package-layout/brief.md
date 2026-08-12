# Outcome

把 M01–M03 形成的 `venagent` 扁平模块重构为按能力优先聚合的 Python package，使 conversation、agent、基础设施和 HTTP 边界清晰，并为 M04 及后续 DAG、RAG、工具和子 Agent 扩展提供稳定依赖方向。

# Scope

- 建立顶层能力包 `conversation/` 与 `agent/`，分别承载对话生命周期/导入用例和 Agent graph/runtime/run 能力。
- 建立 `infra/`，按 `persistence/`、`llm/` 与 PostgreSQL platform 生命周期拆分外部实现。
- 建立 `interfaces/http/`，拆分 FastAPI composition、schemas、errors、routes 与 streaming adapter。
- 新增显式根 composition module `bootstrap.py`，保留 `__main__.py` 作为 CLI 入口。
- 更新内部导入、测试导入、setuptools package discovery、package data 与 README 启动路径。
- 删除被新 package 替代的顶层扁平实现文件，不保留同名兼容 shim。

# Non-goals

- 不改变任何 HTTP URL、请求/响应、SSE、错误 code 或 Web UI 行为。
- 不改变 PostgreSQL 表、LangGraph checkpoint、schema 版本、迁移行为或 Docker Compose。
- 不实现 M04 身份授权、M15 恢复、RAG、工具、DAG 或子 Agent 新能力。
- 不把纯数据容器强行包装成复杂领域实体，也不引入依赖注入框架。

# Acceptance examples

- 现有同步聊天、SSE、取消、线程删除、旧会话导入、健康状态与 PostgreSQL 重启恢复测试在新导入路径下全部通过。
- `python -m venagent` 和 `python -m venagent migrate` 保持可用；README 的直接 Uvicorn 目标指向新 HTTP composition root。
- `conversation` 不导入 `infra`；仓储能力通过消费方拥有的 `Protocol` 注入，PostgreSQL/内存 adapter 反向实现该契约。
- `agent` 不导入 FastAPI、psycopg 或具体 provider SDK；HTTP 与 infra 依赖只在 composition root 装配。
- 顶层 `venagent/` 不再保留 `agent_loop.py`、`api.py`、`conversation.py`、`llm.py`、`persistence.py`、`runs.py`、`streaming.py` 扁平实现。

# Constraints and invariants

- 采用用户确认的短命名 `infra`，不使用 `infrastructure`；不新增顶层 `app` 大桶。
- 采用 ECC feature/domain-first 原则：能力优先聚合，小文件、高内聚、低耦合；Protocol 位于消费能力一侧。
- 借鉴 AGI-saber 的 `infra`、`persistence`、`llm`、`interfaces/http` 项目语言，但不迁移其 chat history、snapshot 或 shortterm 实现。
- 保持 Python 3.11、FastAPI、LangGraph、Pydantic 与现有依赖版本范围。
- 保持 `venagent` 顶层公开导出 `AgentLoop`、`AgentResult` 和 `build_local_model`，避免包级公共入口无必要破坏。

# Decisions

- 用户确认 feature-first 目录，以 `conversation`、`agent` 为核心能力包，`infra` 与 `interfaces/http` 为边缘 adapter。
- 用户明确选择 `infra` 替代 `infrastructure`；`application` 不建立顶层包，应用用例直接位于能力包内。
- 本次执行真实移动和拆分，不保留旧扁平模块 shim；稳定用户入口由 HTTP/CLI 契约而非内部模块路径定义。
- composition wiring 集中在 `bootstrap.py` 与 `interfaces/http/app.py`，不使用隐藏 service locator。
- 用户已用“按这个修改文件结构”明确批准该目录和边界实施。

# Open questions

无。

# Verification expectations

- 运行完整 pytest，包括真实 PostgreSQL集成路径（环境可用时）。
- 运行 Python compileall、依赖完整性、Web 脚本语法、Compose 配置与 `git diff --check`。
- 增加架构测试，验证新 package 存在、旧扁平模块消失及禁止的反向依赖不存在。
- 运行 Comet 有界文本检查并记录所有派生 acceptance evidence。
