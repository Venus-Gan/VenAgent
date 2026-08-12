# Feature-first Package Layout 完整目标规格

## 1. 目标

VenAgent SHALL 保持 feature-first Python/Vue 结构，并随真实能力重构现有 package。目录体现所有权和依赖方向，不为 M05--M09 预建空 package、共享层或 adapter。

## 2. Python 能力边界

- `conversation/` 拥有 Conversation、ConversationMessage、消息/run 创建用例、对话查询/标题/删除和消费方 store/authorization ports。
- `agent/` 拥有 LangGraph State、graph、runtime contract、run lifecycle/finalizer/reconciler、scheduler/claim 协调、ContextProjection基础和 model port。
- `ownership/` 拥有 owner/user/session、RunGrant/ExecutionAuthorization use case、身份错误与消费方 ports。
- `infra/platform/` 实现 PostgreSQL/内存业务 adapter、显式 schema migration、官方 checkpointer装配与启动模式选择；不得拥有 conversation/agent/ownership用例。
- `infra/llm/` 保持 provider/config adapter；具体 SDK延迟导入且不泄漏到 agent领域。
- `interfaces/http/` 只拥有 FastAPI依赖、Pydantic schema、HTTP错误映射、SSE transport与路由；不得直接写 AgentRun状态或执行业务事务。
- `bootstrap.py` 是唯一 composition root，显式装配 store、checkpointer、services、scheduler、lifespan与启动报告；不得使用全局 service locator或导入副作用。

具体文件可按实现内聚性合并或拆分；上述是职责边界，不要求为每个名词创建一个文件。

## 3. 依赖方向

- conversation、agent、ownership 不得导入 FastAPI、psycopg、具体 provider SDK或 `venagent.infra` adapter。
- 领域/application package通过自身消费方 Protocol依赖存储、模型、时钟、授权和通知；infra实现这些端口。
- agent 不拥有 owner/session/credential业务事实；conversation不解析 Cookie；ownership不执行 LangGraph。
- HTTP route只解析协议与 actor，调用 application service并映射结果；SSE adapter只观察 projection，不拥有 run生命周期。
- checkpointer配置只由 agent公开 helper产生；其他 package不得散布 `thread_id` 拼装或查询私有表。

## 4. 前端边界

- 保持 `web/src/app/`、`web/src/modules/chat/` 与 `web/src/modules/ownership/` 的当前基线；chat模块拥有 conversation/message/run/partial视图状态和交互。
- 组件不持有服务端业务真相；Pinia actions调用 API、reducers/selectors收敛投影，组件发命令并渲染。
- 当前 change不得新增 memory、tool、task、RAG、operator或通用 shared feature module。只有至少两个已实现能力存在稳定复用时才创建共享抽象。

## 5. 旧实现移除

- 旧 ThreadRecord、TurnRecord、ConversationRun、ThreadLease、conversation-scoped AgentLoop投影、进程内权威 RunRegistry与旧 `/api/threads`、`/api/chat*` 实现 SHALL 移除，不保留长期 shim。
- 顶层公开入口可以继续导出仍真实存在且稳定的构建能力，但不得维持与新运行模型冲突的 `AgentLoop` 语义只为旧测试兼容。
- 测试迁移到新公开 contract；旧内部 import path不属于兼容范围。

## 6. 注释与可维护性

- claim/fencing、checkpoint/业务发布顺序、RunGrant不随 session撤销、断连不取消和 partial非权威等非显然处 SHALL 添加简洁“为什么”注释。
- 不为显然赋值逐行写注释，不用通用 manager/helper掩盖明确领域职责。
- 公共 Python函数与 Protocol使用类型标注，错误显式，资源用 context/lifespan管理；async路径不得执行可避免的阻塞 I/O。

## 7. CLI 与部署

- `python -m venagent` 和显式 migration命令保持可用；普通启动不执行 DDL。
- Vite开发代理与 FastAPI生产静态托管保持现有部署基线，前后端新协议作为一个协调发布面，不允许半套新旧 API进入可用状态。
- 健康与启动报告由 composition root实际装配结果生成，不通过自动发现猜测未来组件。

## 8. 验收

- 架构测试证明禁止依赖不存在，旧模型/路由/权威 registry已移除，checkpointer映射集中。
- 全量 Python与前端测试使用新公开 contract；compileall、typecheck和构建通过。
- composition root测试证明 temporary/durable装配、scheduler/lifespan关闭和资源释放明确，无重复后台任务。
- 代码审查确认没有为 M05--M09预建目录、事件总线、规则引擎或共享空壳。
