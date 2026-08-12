# AGI-saber 代码审计

## 1. 审计基线与方法

- 审计对象：`D:\VSCProject\AGI-saber`
- Git 基线：`fead7687a82965b3c0106728089ccde0cc0eb3e8`
- 基线日期：2026-07-17 22:15:42 +08:00
- 工作树：审计时干净
- 规模：178 个 tracked 文件；116 个 Go 文件，约 17,427 行；20 个 Go 测试文件、112 个测试函数。
- 验证：`go test ./... -timeout 30s -count=1` 通过。首次无 per-package timeout 的运行因依赖/编译预热超过宿主 120 秒而被终止，第二次在 31 秒完成。
- 前端：仓库没有 `web/node_modules`，且 `package.json` 未定义单元测试脚本，因此本次未下载依赖、未执行前端构建或测试。

本审计以源码为准，README 为辅助。`docs/architecture` 中部分文档仍描述旧的单文件 `agent.go`、旧目录名和极低测试量，已与当前 DDD 风格目录及 112 个测试不一致，不能直接作为 VenAgent 规划依据。

## 2. 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Go 1.24、`chi`、标准库 HTTP/SSE、`slog` |
| 鉴权 | JWT v5、bcrypt、Bearer token |
| 前端 | Vue 3、Pinia、Vite 5、原生 Fetch/SSE、localStorage |
| 模型 | 自研 OpenAI-compatible HTTP/SSE client；主模型和 fast model；独立 embedding endpoint |
| 关系数据 | PostgreSQL 16、`lib/pq`、启动期内嵌 DDL |
| 向量检索 | Milvus 2.4、etcd、MinIO |
| 关键词检索 | Elasticsearch 8 |
| 图数据 | Neo4j 5，知识图谱与图增强记忆共用 |
| 事件 | Kafka KRaft，主要发布聊天与审计事件 |
| 沙箱 | Docker/local/mock 三后端；正则策略、资源限制、默认断网 |
| 部署 | Docker Compose 七个基础设施服务；后端轻量 Alpine 镜像；前端独立构建 |

VenAgent 当前实际依赖为 Python 3.11、FastAPI 0.139.2、LangGraph 1.2.9、LangChain Core 1.5.0、LangChain OpenAI 1.4.0。已安装版本包含内存 checkpointer 与 streaming runtime 能力，可支持下一阶段，但具体 API 在该阶段单独核对。

## 3. 模块与功能清单

| 能力域 | 旧项目实现 | 关键功能 | 审计判断 |
| --- | --- | --- | --- |
| 启动与装配 | `cmd/server` | 配置、平台连接、仓储、Agent、HTTP、优雅关停 | 保留装配思想，改用 FastAPI lifespan 与明确 Ports |
| 配置 | `config` | YAML、环境变量插值、主/快模型、全部基础设施参数 | 需重写；配置过于集中，开发密码和占位值容易误用 |
| HTTP | `interfaces/http` | REST、SSE、JWT、request ID、CORS、panic recovery、pprof | 保留外部行为候选；用 FastAPI/Pydantic 重建契约 |
| 认证 | `application/auth`、`domain/auth` | 注册、登录、JWT、bcrypt | 延后到持久化阶段；先保留可选 `owner_id` 边界 |
| Agent 编排 | `application/chat` | prepare/dispatch/finalize、路由、ReAct、取消、快照 | 行为参考，必须以 LangGraph 状态图重写 |
| 任务图 | `domain/graph`、`runtime_graph.go` | DAG、拓扑层、并行、竞速、重试、replan | 后期选择性重建，不进入早期会话/记忆阶段 |
| 子 Agent | `subagents.go` | research/writer/review/doc 固定流水线 | 属于高阶交付能力，延后；不作为基础运行时前提 |
| 对话历史 | `memory/shortterm`、`chathistory` | 最近 N 轮、按用户内存桶、PG 懒加载/write-through | 语义需改：按 `thread_id` 隔离，用户只是所有者 |
| 偏好 | `memory/preference` | 规则与 LLM 抽取、KV、PG 持久化 | 可保留产品意图，需显式用户确认、来源和可删除性 |
| 长期记忆 | `memory/longterm`、`mem_writer.go` | 分类、embedding/TF 召回、重要性、去重、衰减、TTL | 选择性保留；先定义记忆契约和安全策略再实现 |
| 记忆安全 | `poison.go`、`conflict.go` | PII/injection 隔离、quarantine、superseded、冲突判断 | 核心安全意图值得保留，但规则与日志需要重审 |
| 图记忆 | `memory/graph` | Neo4j 相似/时序边、图扩展召回、中心度保护 | 高成本可选能力；长期记忆稳定后再评估收益 |
| Prompt 上下文 | `domain/promptctx` | profile/planner/task/tool/constraints/recall slots 与预算 | 保留“上下文有来源和预算”的原则；用 LangGraph state/middleware 重建 |
| RAG | `domain/rag` | recursive split、父子块、Milvus+ES+Neo4j、RRF、rewrite、rerank | 分阶段重建；先最小可评测检索，再选择混合与图增强 |
| 文档库 | `domain/document`、`documentrepo` | 文本/PDF 解析、版本化 Markdown、重新入库 | 与 RAG 同阶段；保留版本/来源概念 |
| 工具 | `domain/tool`、`infrastructure/tool` | search、结构化结果、MCP HTTP | 用 LangChain tool contract 重建；MCP 先做安全边界 |
| 沙箱 | `domain/sandbox`、`infrastructure/sandbox` | 校验、Docker/local/mock、审计、产物目录 | 工具阶段引入；local 默认禁用，危险动作需审批 |
| Skill | `domain/skill`、`application/skill`、`skillhub` | 内置 prompt skill、GitHub 描述包装、安装/开关 | 延后；当前不是可执行插件系统，不应作为早期目标 |
| 事件与观测 | `eventbus`、`pkg/logger`、pprof | Kafka 事件、结构化日志、request ID、pprof | 早期保留轻量追踪；Kafka/pprof 按真实需求再引入 |
| Web | `web/src` | 登录、聊天/SSE、思考步骤、知识库、文档、Skill、会话 | 保留视觉与核心交互；按后端阶段逐项解锁，不整页复制 |

## 4. 关键数据流

### 4.1 对话

`HTTP → JWT userID → prepare → 写 STM/PG → 偏好抽取 → 上下文装配 → 路由 → ReAct/RAG → finalize → 写 assistant 历史 → 长期记忆抽取/合并 → SSE done`

值得保留的是 prepare/execute/finalize 的职责划分；不应保留的是单个 `UnifiedAgent` 持有跨请求共享的当前任务、task memory、tool tracker 与全局 cancel 集合。

### 4.2 旧项目的“记忆”不是一个模块

| 状态 | 当前主键/存储 | 生命周期 | 正确归类 |
| --- | --- | --- | --- |
| UI 会话 | localStorage session ID | 浏览器本地 | 产品会话 |
| STM | `userID` + 内存桶/PG chat_history | 最近 5 轮 | 对话线程历史 |
| Preference | `userID` + 内存/PG KV | 长期 | 用户资料/偏好 |
| LTM | `userID` + 内存/PG/vector/graph | 长期 | 语义业务记忆 |
| TaskMem | Agent 单例 ring buffer | 当前任务 | 运行时观察 |
| Snapshot | task ID + PG JSON | 任务执行 | 业务执行快照 |

UI 的 session ID 没有发送给后端，后端短期记忆只按 userID 分桶，因此同一用户的多个“新对话”会共享服务端历史。这是 VenAgent 下一阶段必须纠正的首要语义问题。

### 4.3 RAG

上传文档经解析和递归切分生成子块/父块，写 PostgreSQL 元数据，并按可用性写入 Milvus、Elasticsearch、Neo4j。查询先做 history-aware 多查询改写，再扩大召回、RRF 融合、LLM rerank，最后生成回答。功能丰富，但一次性引入会同时带来模型、向量维度、三种数据库、索引一致性和评测问题。

### 4.4 ReAct 与任务图

Planner 生成自定义 DAG；GraphRuntime 用 goroutine、信号量、race group 和层间 replan 执行，再由 Generator 汇总。它不是 LangGraph checkpoint 模型；任务快照也不能直接等价为对话 checkpoint。该能力应在工具和持久化边界稳定后重新取舍。

## 5. 经过验证的优点

- Go 包依赖层次较清晰，当前测试套件通过。
- 长期记忆明确考虑多用户隔离、quarantine、superseded、去重和衰减。
- RAG 具有降级、父子块、混合检索、改写与重排思想。
- SSE、取消、request ID、结构化日志和优雅关停已有产品经验。
- SkillHub 固定 GitHub API 域名且不执行仓库代码，安全边界相对明确。
- 外部基础设施以接口/仓储形式注入的方向值得继承。

## 6. 必须避免直接迁移的问题

1. **会话错位**：前端 session 与后端 userID 历史不一致。
2. **跨请求共享状态**：当前任务、task memory、tool tracker 和 `Cancel()` 是 Agent 单例级别，并发请求可能互相覆盖或被一起取消。
3. **状态概念混杂**：聊天历史、长期记忆、任务快照、工具观察都被“记忆/恢复”语言覆盖。
4. **MCP 安全不足**：注册端点可指向任意 URL，缺少 SSRF/私网/重定向策略和响应体上限；错误载荷可能直接回传。
5. **沙箱默认风险**：allowlist 默认关闭，local backend 与正则拦截不足以构成强隔离。
6. **敏感数据日志**：长期记忆写入日志包含提取后的 key/value；模型错误也可能携带供应商响应体。
7. **配置误用**：占位符会被识别为真实配置；开发基础设施凭据写在模板中；语义校验不足。
8. **降级不透明**：大量 fail-open/mocked fallback 容易让界面“可用”但实际能力未工作。
9. **测试不均衡**：112 个测试集中在少数包；短期记忆、图记忆、LLM、全部仓储、平台连接、沙箱和大部分前端没有直接测试。
10. **旧文档漂移**：部分架构报告仍描述已拆除的旧目录和旧规模，说明文档不能替代代码审计。

## 7. 取舍建议

### 保留为长期产品意图

- Web 聊天体验、SSE、取消与状态展示。
- 明确的会话线程、可恢复运行和分层记忆。
- 工具调用、受控 MCP、沙箱和产物交付。
- 文档库与可评测 RAG。
- 用户数据隔离、记忆审计、冲突替代和可删除性。

### 重写而非移植

- Agent/任务图：使用 LangGraph state、node、edge、checkpointer 与 stream。
- API：使用 FastAPI/Pydantic 和稳定事件契约。
- 模型：使用 LangChain provider adapter，不维护自研 OpenAI 协议客户端。
- 持久化：定义 Ports，分别实现 conversation/checkpoint/memory/document repository。
- 前端会话：必须发送稳定 `thread_id`，不再只存在 localStorage。

### 延期并要求收益证据

- Neo4j 图记忆与知识图谱召回。
- Kafka 事件平台。
- 竞速 DAG、自动 replan、多 Agent 固定流水线。
- GitHub Skill 广场和可安装插件系统。
- Milvus + Elasticsearch + Neo4j 三路同时部署。

## 8. 审计结论

`AGI-saber` 应作为能力地图和失败经验库，而不是迁移源。VenAgent 的正确路线是先建立线程、状态和安全边界，再依次加入持久化、长期记忆、工具、RAG 和高阶编排。任何外部基础设施都应由阶段验收证明其必要性。
